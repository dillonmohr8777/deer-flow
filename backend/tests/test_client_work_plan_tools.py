"""Synthetic authenticated Gateway -> worker -> ToolNode -> real SQL acceptance."""

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.graph import END, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode
from org_isolation_fixtures import org_world_pooled  # noqa: F401
from pydantic import ValidationError
from sqlalchemy import func, select
from test_client_portal import BASE, CUSTOMER_ORG, CUSTOMER_STORAGE, USER_A, USER_B, USER_C, _compose, _http, _work_plan, auth_headers, project_work_world, world  # noqa: F401

from app.gateway import services
from deerflow.persistence.approvals.model import PendingActionRow
from deerflow.persistence.audit_events import AuditEventRepository
from deerflow.persistence.board.model import BoardPortalRow, BoardThreadRow
from deerflow.persistence.clients.model import ClientAssignmentRow, ClientRow
from deerflow.persistence.organizations.model import OrganizationMemberRow, OrganizationRow
from deerflow.persistence.run.model import RunRow
from deerflow.persistence.thread_meta.model import ThreadMetaRow
from deerflow.persistence.user.model import UserRow
from deerflow.runtime.context_keys import CLIENT_WORK_PLAN_ACCESS_CONTEXT_KEY as KEY
from deerflow.runtime.runs import worker
from deerflow.tools.builtins.client_work_plan import read_client_work_plan, update_client_work_plan
from deerflow.tools.client_work_plan_access import CLIENT_WORK_PLAN_TOOL_NAMES, ClientWorkPlanAccess, matching_client_work_plan_access

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def org_world(org_world_pooled):  # noqa: F811
    return org_world_pooled


@pytest_asyncio.fixture
async def tool_world(project_work_world, monkeypatch):  # noqa: F811
    w = project_work_world
    w.app.state.audit_repo = AuditEventRepository(w.sf)
    w.script = [("read_client_work_plan", {})]
    w.results, w.capabilities, w.contexts, w.graphs = [], [], [], []
    w.before_call = None

    def factory(*, config):
        from deerflow.agents.lead_agent.agent import _append_client_work_plan_tools_if_bound

        context = config["context"]
        w.contexts.append(context)
        w.capabilities.append(context.get(KEY))
        tools = []
        _append_client_work_plan_tools_if_bound(tools, context)

        async def scripted(state):
            outputs = [message for message in state["messages"] if isinstance(message, ToolMessage)]
            if outputs:
                w.results.append(json.loads(outputs[-1].content))
            index = len(outputs)
            if index >= len(w.script):
                return {"messages": [AIMessage(content="Synthetic record-only run finished")]}
            if w.before_call is not None:
                await w.before_call(index, context)
            name, args = w.script[index]
            return {"messages": [AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"plan-call-{index}"}])]}

        builder = StateGraph(MessagesState)
        builder.add_node("scripted", scripted)
        builder.add_node("tools", ToolNode(tools))
        builder.set_entry_point("scripted")
        builder.add_conditional_edges("scripted", lambda state: "tools" if state["messages"][-1].tool_calls else END)
        builder.add_edge("tools", "scripted")
        graph = builder.compile(checkpointer=w.app.state.checkpointer)
        w.graphs.append(graph)
        return graph

    monkeypatch.setattr(services, "run_agent", worker.run_agent)
    monkeypatch.setattr(services, "resolve_agent_factory", lambda *_: factory)
    return w


async def _start(w, client, *, project=None):
    created = await _compose(client, auth_headers(USER_B, CUSTOMER_ORG))
    response = await client.post(f"{BASE}/{created['id']}/work", headers=auth_headers(USER_C, CUSTOMER_ORG), json={"project_id": project} if project else {})
    assert response.status_code == 200, response.text
    record = w.app.state.run_manager._runs[response.json()["run_id"]]
    await record.task
    assert record.status.value == "success", record.error
    return created["id"], record


def _runtime(access, **changes):
    return SimpleNamespace(
        context={
            KEY: access,
            "actor_user_id": access.actor_id,
            "organization_id": access.organization_id,
            "storage_user_id": access.storage_user_id,
            "thread_id": access.chat_id,
            "run_id": access.run_id,
            "agent_name": "momobot-max",
            "user_role": "user",
            **changes,
        }
    )


@pytest.mark.parametrize("project", [None, "project-a"])
async def test_gateway_tool_reads_updates_conflicts_audits_and_keeps_drafts_independent(tool_world, project):
    w = tool_world
    plan = _work_plan(verifier_user_id=None, status="reported_complete", evidence_refs=[{"kind": "source", "reference": "https://source.invalid/untrusted"}, {"kind": "delivery", "reference": "file:///private/untrusted"}])["plan"]
    w.script = [
        ("read_client_work_plan", {}),
        ("update_client_work_plan", {"expected_revision": 0, "plan": plan}),
        ("update_client_work_plan", {"expected_revision": 0, "plan": {**plan, "outcome": "Stale overwrite"}}),
        ("read_client_work_plan", {}),
    ]
    async with _http(w.app) as client:
        request_id, record = await _start(w, client, project=project)
        first, saved, conflict, live = w.results
        assert first["revision"] == 0 and first["participant_user_ids"] == [USER_C]
        assert saved["revision"] == live["revision"] == 1 and live["plan"] == saved["plan"]
        assert saved["verification"] == "staff_recorded_unverified" and conflict["status"] == 409
        assert saved["recorded_by_user_id"] == USER_C and saved["source"]["id"] == request_id
        async with w.sf() as session:
            portal = await session.get(BoardPortalRow, request_id)
            assert (portal.revision, portal.draft_id, portal.approval_id, portal.published_id) == (0, None, None, None)
            assert await session.scalar(select(func.count()).select_from(PendingActionRow)) == 0
            assert await session.scalar(select(func.count()).select_from(RunRow).where(RunRow.thread_id == record.thread_id)) == 1
        events, _ = await w.app.state.audit_repo.list(organization_id=CUSTOMER_ORG, action_prefix="client_portal.work_plan.saved")
        assert len(events) == 1 and events[0]["actor_user_id"] == USER_C and events[0]["target_id"] == request_id
        assert events[0]["details"] == {"source": "client_work_plan_tool", "storage_user_id": CUSTOMER_STORAGE, "client_id": "client-a", "revision": 1}
        assert "untrusted" not in json.dumps(events)
        assert KEY not in json.dumps(record.kwargs) and all(KEY not in context for context in w.contexts)
        from deerflow.runtime.checkpoint_state import CheckpointStateAccessor

        snapshot = await CheckpointStateAccessor.bind(w.graphs[-1], w.checkpointer).aget({"configurable": {"thread_id": record.thread_id}})
        assert KEY not in json.dumps({"config": snapshot.config, "metadata": snapshot.metadata, "values": snapshot.values}, default=str)
        # HTTP draft writes use their own revision and cannot lose the plan.
        draft = await client.post(f"{BASE}/{request_id}/draft", headers=auth_headers(USER_C, CUSTOMER_ORG), json={"body": "Human unsent draft", "expected_revision": 0})
        assert draft.status_code == 200, draft.text
        assert (await client.get(f"{BASE}/{request_id}/work-plan", headers=auth_headers(USER_C, CUSTOMER_ORG))).json()["revision"] == 1


@pytest.mark.parametrize("revocation", ["assignment", "membership", "disabled", "role", "internal_role", "client", "organization", "storage", "client_binding", "chat_binding"])
async def test_live_revocation_between_admission_and_actual_tool_denies_without_write(tool_world, revocation):
    w = tool_world
    w.script = [("update_client_work_plan", _work_plan(verifier_user_id=None)), ("read_client_work_plan", {})]

    async def revoke(index, context):
        if index:
            return
        access = context[KEY]
        async with w.sf() as session, session.begin():
            if revocation == "assignment":
                (await session.get(ClientAssignmentRow, ("client-a", USER_C))).role = "contributor"
            elif revocation == "membership":
                (await session.get(OrganizationMemberRow, (CUSTOMER_ORG, USER_C))).status = "inactive"
            elif revocation == "disabled":
                (await session.get(UserRow, USER_C)).disabled_at = datetime.now(UTC)
            elif revocation == "role":
                (await session.get(UserRow, USER_C)).system_role = "client"
            elif revocation == "internal_role":
                (await session.get(UserRow, USER_C)).system_role = "internal"
            elif revocation == "client":
                (await session.get(ClientRow, "client-a")).status = "inactive"
            elif revocation == "organization":
                (await session.get(OrganizationRow, CUSTOMER_ORG)).status = "inactive"
            elif revocation == "storage":
                (await session.get(ThreadMetaRow, access.chat_id)).user_id = USER_A
            elif revocation == "client_binding":
                (await session.get(BoardThreadRow, access.request_id)).client_id = "client-b"
            else:
                (await session.get(BoardPortalRow, access.request_id)).work_chat_id = "rebound-chat"

    w.before_call = revoke
    async with _http(w.app) as client:
        request_id, _ = await _start(w, client)
    assert [result["status"] for result in w.results] == [404, 404]
    async with w.sf() as session:
        portal = await session.get(BoardPortalRow, request_id)
        assert portal.work_plan_revision == 0 and portal.work_plan is None
    assert (await w.app.state.audit_repo.list(organization_id=CUSTOMER_ORG, action_prefix="client_portal.work_plan.saved"))[0] == []


@pytest.mark.parametrize(
    "changes",
    [
        {"actor_user_id": USER_A},
        {"storage_user_id": USER_A},
        {"organization_id": "other"},
        {"thread_id": "other"},
        {"run_id": "other"},
        {"agent_name": "other"},
        {"user_role": "client"},
        {"is_subagent": True},
        {"channel_name": "slack"},
        {"is_bootstrap": True},
    ],
)
async def test_runtime_binding_forgery_is_denied(tool_world, changes):
    w = tool_world
    async with _http(w.app) as client:
        await _start(w, client)
    runtime = _runtime(w.capabilities[0], **changes)
    assert json.loads(await read_client_work_plan.coroutine(runtime))["status"] == 404
    assert json.loads(await update_client_work_plan.coroutine(0, _work_plan()["plan"], runtime))["status"] == 404


@pytest.mark.parametrize(
    "change",
    [
        {"assignee_user_id": USER_B},
        {"verifier_user_id": "missing"},
        {"dependency_thread_ids": ["missing"]},
        {"dependency_thread_ids": ["same", "same"]},
        {"status": "verified_complete"},
        {"status": "reported_complete", "evidence_refs": []},
        {"due_at": "2026-10-25"},
        {"verified": True},
    ],
)
async def test_actual_tool_reuses_http_plan_validation(tool_world, change):
    w = tool_world
    payload = _work_plan(verifier_user_id=None, **change) if "verifier_user_id" not in change else _work_plan(**change)
    w.script = [("update_client_work_plan", payload)]
    async with _http(w.app) as client:
        request_id, _ = await _start(w, client)
        tool_error = w.results[0]["status"]
        response = await client.put(f"{BASE}/{request_id}/work-plan", headers=auth_headers(USER_C, CUSTOMER_ORG), json=payload)
        assert response.status_code == tool_error
    assert tool_error in {404, 422}


async def test_saved_participants_are_revalidated_and_no_directory_is_invented(tool_world):
    w = tool_world
    async with _http(w.app) as client:
        request_id, _ = await _start(w, client)
        saved = await client.put(f"{BASE}/{request_id}/work-plan", headers=auth_headers(USER_C, CUSTOMER_ORG), json=_work_plan())
        assert saved.status_code == 200
    runtime = _runtime(w.capabilities[0])
    result = json.loads(await read_client_work_plan.coroutine(runtime))
    assert result["participant_user_ids"] == sorted([USER_A, USER_C])
    async with w.sf() as session, session.begin():
        (await session.get(OrganizationMemberRow, (CUSTOMER_ORG, USER_A))).status = "inactive"
    assert json.loads(await read_client_work_plan.coroutine(runtime))["status"] == 404
    assert json.loads(await update_client_work_plan.coroutine(1, _work_plan(verifier_user_id=None)["plan"], runtime))["status"] == 404


async def test_worker_only_hydrates_host_capability_and_cleans_both_config_carriers():
    forged, host = {"authorized": True}, object()
    config = {"context": {KEY: forged}, "configurable": {KEY: forged}}
    context = worker._build_runtime_context("chat", "run", config["context"])
    worker._install_runtime_context(config, context)
    assert KEY not in config["context"] and KEY not in config["configurable"]
    assert worker.RunContext(checkpointer=None).client_work_plan_access is None
    context = worker._build_runtime_context("chat", "run", {}, client_work_plan_access=host)
    worker._install_runtime_context(config, context)
    assert context[KEY] is host
    worker._release_run_scoped_references([config], context, None)
    assert KEY not in context and KEY not in config["context"]
    for section in ("context", "configurable"):
        admitted = services.build_run_config("chat", {section: {KEY: forged}}, None)
        assert KEY not in admitted.get("context", {}) and KEY not in admitted.get("configurable", {})


async def test_schema_accepts_no_model_identity_and_requires_strict_explicit_revision():
    assert set(read_client_work_plan.tool_call_schema.model_fields) == set()
    assert set(update_client_work_plan.tool_call_schema.model_fields) == {"expected_revision", "plan"}
    for args in ({"plan": {}}, {"expected_revision": "0", "plan": {}}, {"expected_revision": True, "plan": {}}, {"expected_revision": 0, "plan": {}, "actor_id": USER_A}, {"expected_revision": 0, "plan": {}, "request_id": "other"}):
        with pytest.raises(ValidationError) as error:
            update_client_work_plan.args_schema.model_validate(args)
        assert any(issue["loc"] != ("runtime",) for issue in error.value.errors())


async def test_concurrent_http_and_tool_plan_edits_have_one_winner_and_keep_human_draft(tool_world):
    w = tool_world
    async with _http(w.app) as client:
        request_id, _ = await _start(w, client)
        builder = StateGraph(MessagesState)
        builder.add_node("tools", ToolNode([update_client_work_plan]))
        builder.set_entry_point("tools")
        builder.add_edge("tools", END)
        graph = builder.compile()
        payload = _work_plan(verifier_user_id=None)
        tool_payload = {**payload, "plan": {**payload["plan"], "outcome": "Concurrent tool record"}}
        ui, tool, draft = await asyncio.gather(
            client.put(f"{BASE}/{request_id}/work-plan", headers=auth_headers(USER_C, CUSTOMER_ORG), json=payload),
            graph.ainvoke({"messages": [AIMessage(content="", tool_calls=[{"name": "update_client_work_plan", "id": "race", "args": tool_payload}])]}, context=_runtime(w.capabilities[0]).context),
            client.post(f"{BASE}/{request_id}/draft", headers=auth_headers(USER_C, CUSTOMER_ORG), json={"body": "Concurrent human draft", "expected_revision": 0}),
        )
        result = json.loads(tool["messages"][-1].content)
        assert sorted([ui.status_code, result.get("status", 200)]) == [200, 409]
        assert draft.status_code == 200, draft.text
        live = (await client.get(f"{BASE}/{request_id}", headers=auth_headers(USER_C, CUSTOMER_ORG))).json()
        plan = (await client.get(f"{BASE}/{request_id}/work-plan", headers=auth_headers(USER_C, CUSTOMER_ORG))).json()
        assert plan["revision"] == 1 and live["draft"]["body"] == "Concurrent human draft"
        events, _ = await w.app.state.audit_repo.list(organization_id=CUSTOMER_ORG, action_prefix="client_portal.work_plan.saved")
        assert len(events) == 1 and events[0]["actor_user_id"] == USER_C


async def test_gateway_forged_capability_is_stripped_and_nonportal_private_contact_runs_get_none(tool_world):
    w = tool_world
    async with _http(w.app) as client:
        request_id, record = await _start(w, client)
        payload = {
            "assistant_id": "momobot-max",
            "input": {"messages": [{"role": "user", "content": "Synthetic continuation"}]},
            "context": {KEY: {"authorized": True}, "actor_user_id": USER_A},
            "config": {"context": {KEY: {"client_id": "other"}}, "configurable": {KEY: {"request_id": "other"}}},
        }
        response = await client.post(f"/api/threads/{record.thread_id}/runs", headers=auth_headers(USER_C, CUSTOMER_ORG), json=payload)
        assert response.status_code == 200, response.text
        resumed = w.app.state.run_manager._runs[response.json()["run_id"]]
        await resumed.task
        assert w.capabilities[-1].request_id == request_id and w.capabilities[-1].actor_id == USER_C
        assert KEY not in json.dumps(resumed.kwargs)
        # Nonportal/private threads have no server-owned request binding.
        w.script = []
        generic = await client.post(f"/api/threads/{record.thread_id}/runs", headers=auth_headers(USER_C, CUSTOMER_ORG), json={"assistant_id": "lead_agent", "input": {"messages": [{"role": "user", "content": "Generic run"}]}})
        assert generic.status_code == 200, generic.text
        await w.app.state.run_manager._runs[generic.json()["run_id"]].task
        assert w.capabilities[-1] is None
        for organization in (CUSTOMER_ORG, None):
            thread = await client.post("/api/threads", headers=auth_headers(USER_C, organization), json={})
            assert thread.status_code == 200, thread.text
            response = await client.post(f"/api/threads/{thread.json()['thread_id']}/runs", headers=auth_headers(USER_C, organization), json=payload)
            assert response.status_code == 200, response.text
            await w.app.state.run_manager._runs[response.json()["run_id"]].task
            assert w.capabilities[-1] is None
        count = len(w.capabilities)
        denied = await client.post(f"{BASE}/{request_id}/work", headers=auth_headers(USER_B, CUSTOMER_ORG), json={})
        assert denied.status_code == 404 and len(w.capabilities) == count


@pytest.mark.parametrize("case", ["staff", "client", "forged", "other_agent", "subagent", "channel", "actor", "storage", "organization", "run"])
async def test_real_lead_assembly_adds_only_matching_bound_staff_tools(monkeypatch, tmp_path, case):
    import test_momobot_max_assembly as assembly

    cap = ClientWorkPlanAccess("actor", "org", "storage", "client", "request", "chat", "run", AsyncMock(), AsyncMock(), AsyncMock())
    context = _runtime(cap).context
    if case == "forged":
        context[KEY] = {"authorized": True}
    elif case == "other_agent":
        context["agent_name"] = "other"
    elif case == "subagent":
        context["is_subagent"] = True
    elif case == "channel":
        context["channel_name"] = "slack"
    elif case in {"actor", "storage", "organization", "run"}:
        context[{"actor": "actor_user_id", "storage": "storage_user_id", "organization": "organization_id", "run": "run_id"}[case]] = "foreign"
    role = "client" if case == "client" else "user"
    context["user_role"] = role
    # An unrelated agent's loader is outside this fixture; the same matching gate denies it.
    if case == "other_agent":
        assert matching_client_work_plan_access(context) is None
        return
    _, captured = await assembly._assemble(monkeypatch, tmp_path, role=role, app=assembly._app_config(), context=context)
    names = {tool.name for tool in captured["tools"]}
    assert names.intersection(CLIENT_WORK_PLAN_TOOL_NAMES) == (set(CLIENT_WORK_PLAN_TOOL_NAMES) if case == "staff" else set())


async def test_role_authorization_can_deny_bound_tools(monkeypatch, tmp_path):
    import test_momobot_max_assembly as assembly

    authorization = assembly.example_authorization()
    authorization["provider"]["config"]["roles"]["admin"]["tools"] = {"allow": "*", "deny": list(CLIENT_WORK_PLAN_TOOL_NAMES)}
    cap = ClientWorkPlanAccess("actor", "org", "storage", "client", "request", "chat", "run", AsyncMock(), AsyncMock(), AsyncMock())
    _, captured = await assembly._assemble(monkeypatch, tmp_path, role="admin", app=assembly._app_config(authorization=authorization), context=_runtime(cap, user_role="admin").context)
    assert set(CLIENT_WORK_PLAN_TOOL_NAMES).isdisjoint(tool.name for tool in captured["tools"])
