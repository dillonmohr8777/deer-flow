"""Synthetic authenticated Gateway -> worker -> ToolNode -> real SQL acceptance."""

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph import END, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode
from org_isolation_fixtures import ORG_A, ORG_S, org_world_pooled  # noqa: F401
from pydantic import ValidationError
from sqlalchemy import func, select
from test_client_portal import BASE, CUSTOMER_ORG, CUSTOMER_STORAGE, USER_A, USER_B, USER_C, _compose, _http, _work_plan, auth_headers, project_work_world, world  # noqa: F401

from app.gateway import services
from deerflow.persistence.approvals.model import PendingActionRow
from deerflow.persistence.audit_events import AuditEventRepository
from deerflow.persistence.board.model import BoardMessageRow, BoardPortalRow, BoardThreadRow
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
            messages = state["messages"]
            latest_user = max((index for index, message in enumerate(messages) if isinstance(message, HumanMessage)), default=-1)
            outputs = [message for message in messages[latest_user + 1 :] if isinstance(message, ToolMessage)]
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


async def _add_directory_user(w, user_id, *, email=None, membership_role="member", membership_status="active", organization_id=CUSTOMER_ORG, system_role="user", disabled_at=None, assignment=None):
    now = datetime.now(UTC)
    async with w.sf() as session, session.begin():
        session.add(UserRow(id=user_id, email=email or f"{user_id}@example.test", password_hash=None, system_role=system_role, needs_setup=False, token_version=0, disabled_at=disabled_at, created_at=now))
        session.add(OrganizationMemberRow(organization_id=organization_id, user_id=user_id, role=membership_role, status=membership_status))
        if assignment is not None:
            client_id, assignment_org, assignment_role = assignment
            session.add(ClientAssignmentRow(client_id=client_id, user_id=user_id, organization_id=assignment_org, role=assignment_role))


async def _run_tool_commands(w, client, thread_id, commands):
    w.script = commands
    w.results = []
    response = await client.post(
        f"/api/threads/{thread_id}/runs",
        headers=auth_headers(USER_C, CUSTOMER_ORG),
        json={"assistant_id": "momobot-max", "input": {"messages": [{"role": "user", "content": "Continue the recorded plan"}]}},
    )
    assert response.status_code == 200, response.text
    record = w.app.state.run_manager._runs[response.json()["run_id"]]
    await record.task
    assert record.status.value == "success", record.error
    return record, list(w.results)


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
    plan = _work_plan(
        assignee_user_id=USER_A, verifier_user_id=None, status="reported_complete", evidence_refs=[{"kind": "source", "reference": "https://source.invalid/untrusted"}, {"kind": "delivery", "reference": "file:///private/untrusted"}]
    )["plan"]
    w.script = [
        ("read_client_work_plan", {}),
        ("update_client_work_plan", {"expected_revision": 0, "plan": plan}),
        ("update_client_work_plan", {"expected_revision": 0, "plan": {**plan, "outcome": "Stale overwrite"}}),
        ("read_client_work_plan", {}),
    ]
    async with _http(w.app) as client:
        request_id, record = await _start(w, client, project=project)
        first, saved, conflict, live = w.results
        first_page = first["participants"]
        assert first["revision"] == 0 and first["current_actor_user_id"] == USER_C
        assert {item["user_id"] for item in first_page["items"]} == {USER_A, USER_C}
        assert first_page["selected_items"] == []
        assert set(first_page["items"][0]) == {"user_id", "email", "role"}
        assert saved["revision"] == live["revision"] == 1 and live["plan"] == saved["plan"]
        assert saved["plan"]["assignee_user_id"] == USER_A
        assert live["participants"]["selected_items"] == [{"user_id": USER_A, "email": "user-a@example.com", "role": "owner"}]
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


async def test_revoked_saved_participant_does_not_block_tool_read_or_repair(tool_world):
    w = tool_world
    w.script = []
    async with _http(w.app) as client:
        request_id, record = await _start(w, client)
        draft = await client.post(f"{BASE}/{request_id}/draft", headers=auth_headers(USER_C, CUSTOMER_ORG), json={"body": "Keep this human draft", "expected_revision": 0})
        assert draft.status_code == 200, draft.text
        async with w.sf() as session:
            draft_id = (await session.get(BoardPortalRow, request_id)).draft_id
        saved = await client.put(f"{BASE}/{request_id}/work-plan", headers=auth_headers(USER_C, CUSTOMER_ORG), json=_work_plan(assignee_user_id=USER_C, verifier_user_id=USER_A))
        assert saved.status_code == 200
        async with w.sf() as session, session.begin():
            (await session.get(OrganizationMemberRow, (CUSTOMER_ORG, USER_A))).status = "inactive"
        repair_plan = _work_plan(assignee_user_id=None, verifier_user_id=None)["plan"]
        _, results = await _run_tool_commands(
            w,
            client,
            record.thread_id,
            [
                ("read_client_work_plan", {}),
                ("update_client_work_plan", {"expected_revision": 1, "plan": repair_plan}),
                ("read_client_work_plan", {}),
            ],
        )
        read, repaired, after = results
        assert read["current_actor_user_id"] == USER_C and read["plan"]["verifier_user_id"] == USER_A
        assert read["participants"]["selected_items"] == [{"user_id": USER_C, "email": "user-c@example.com", "role": "account_manager"}]
        assert "user-a@example.com" not in json.dumps(read)
        assert repaired["revision"] == 2 and repaired["plan"]["verifier_user_id"] is None
        assert after["revision"] == 2 and after["participants"]["selected_items"] == []
        live = (await client.get(f"{BASE}/{request_id}/work-plan", headers=auth_headers(USER_C, CUSTOMER_ORG))).json()
        assert "participants" not in live and "current_actor_user_id" not in live
        async with w.sf() as session:
            portal = await session.get(BoardPortalRow, request_id)
            message = await session.get(BoardMessageRow, portal.draft_id)
            assert (portal.work_plan_revision, portal.revision, portal.draft_id) == (2, 1, draft_id)
            assert message.body == "Keep this human draft"


async def test_gateway_participant_directory_filters_scope_and_tool_assigns_new_eligible_owner(tool_world):
    w = tool_world
    await _add_directory_user(w, "contact-candidate", assignment=("client-a", CUSTOMER_ORG, "client_contact"))
    await _add_directory_user(w, "disabled-candidate", disabled_at=datetime.now(UTC), assignment=("client-a", ORG_S, "account_manager"))
    await _add_directory_user(w, "inactive-candidate", membership_status="inactive", assignment=("client-a", ORG_S, "account_manager"))
    await _add_directory_user(w, "foreign-candidate", membership_role="admin", organization_id=ORG_A)
    await _add_directory_user(w, "client-role-candidate", membership_role="admin", system_role="client")
    await _add_directory_user(w, "unassigned-candidate")
    await _add_directory_user(w, "other-client-candidate", assignment=("client-b", ORG_S, "account_manager"))
    await _add_directory_user(w, "contributor-candidate", assignment=("client-a", ORG_S, "contributor"))
    await _add_directory_user(w, "invalid-member-role-candidate", membership_role="contributor", assignment=("client-a", ORG_S, "account_manager"))
    plan = _work_plan(assignee_user_id=USER_A, verifier_user_id=None)["plan"]
    w.script = [
        ("read_client_work_plan", {}),
        ("update_client_work_plan", {"expected_revision": 0, "plan": plan}),
        ("read_client_work_plan", {}),
    ]
    async with _http(w.app) as client:
        request_id, _ = await _start(w, client)
        first, saved, _ = w.results
        assert first["current_actor_user_id"] == USER_C
        assert {item["user_id"] for item in first["participants"]["items"]} == {USER_A, USER_C}
        assert {item["role"] for item in first["participants"]["items"]} == {"owner", "account_manager"}
        assert saved["plan"]["assignee_user_id"] == USER_A
        directory = await client.get(f"{BASE}/{request_id}/work-plan/participants", headers=auth_headers(USER_C, CUSTOMER_ORG))
        assert directory.status_code == 200, directory.text
        assert directory.headers["cache-control"] == "no-store"
        page = directory.json()
        assert set(page) == {"schema", "source", "items", "selected_items", "limit", "has_more", "next_cursor"}
        assert page["schema"] == "work_plan_participants.v1" and page["source"] == {"thread_id": request_id}
        assert page["selected_items"] == [{"user_id": USER_A, "email": "user-a@example.com", "role": "owner"}]
        assert {item["user_id"] for item in page["items"]} == {USER_A, USER_C}
        assert all(set(item) == {"user_id", "email", "role"} for item in page["items"] + page["selected_items"])
        for hidden in (
            USER_B,
            "contact-candidate",
            "disabled-candidate",
            "inactive-candidate",
            "foreign-candidate",
            "client-role-candidate",
            "unassigned-candidate",
            "other-client-candidate",
            "contributor-candidate",
            "invalid-member-role-candidate",
        ):
            assert hidden not in directory.text


async def test_revoked_listed_participant_cannot_be_saved_and_preserves_plan_and_human_draft(tool_world):
    w = tool_world
    w.script = []
    async with _http(w.app) as client:
        request_id, _ = await _start(w, client)
        staff = auth_headers(USER_C, CUSTOMER_ORG)
        directory = await client.get(f"{BASE}/{request_id}/work-plan/participants", headers=staff)
        assert directory.status_code == 200 and USER_A in {item["user_id"] for item in directory.json()["items"]}
        draft = await client.post(f"{BASE}/{request_id}/draft", headers=staff, json={"body": "Keep this human draft", "expected_revision": 0})
        assert draft.status_code == 200, draft.text
        async with w.sf() as session:
            draft_id = (await session.get(BoardPortalRow, request_id)).draft_id
        async with w.sf() as session, session.begin():
            (await session.get(OrganizationMemberRow, (CUSTOMER_ORG, USER_A))).status = "inactive"
        after_revoke = await client.get(f"{BASE}/{request_id}/work-plan/participants", headers=staff)
        assert after_revoke.status_code == 200 and USER_A not in {item["user_id"] for item in after_revoke.json()["items"]}
        denied = await client.put(f"{BASE}/{request_id}/work-plan", headers=staff, json=_work_plan(assignee_user_id=USER_A, verifier_user_id=None))
        assert denied.status_code == 404, denied.text
        plan = await client.get(f"{BASE}/{request_id}/work-plan", headers=staff)
        assert plan.status_code == 200 and plan.json()["revision"] == 0 and plan.json()["plan"] is None
        async with w.sf() as session:
            portal = await session.get(BoardPortalRow, request_id)
            message = await session.get(BoardMessageRow, portal.draft_id)
            assert (portal.work_plan_revision, portal.revision, portal.draft_id) == (0, 1, draft_id)
            assert message.body == "Keep this human draft"
        events, _ = await w.app.state.audit_repo.list(organization_id=CUSTOMER_ORG, action_prefix="client_portal.work_plan.saved")
        assert events == []


async def test_participant_directory_and_tool_paging_are_bounded_deterministic_and_request_bound(tool_world):
    w = tool_world
    now = datetime.now(UTC)
    async with w.sf() as session, session.begin():
        for index in range(104):
            user_id = f"staff-{index:03d}"
            session.add(UserRow(id=user_id, email=f"{user_id}@example.test", password_hash=None, system_role="user", needs_setup=False, token_version=0, created_at=now))
            session.add(OrganizationMemberRow(organization_id=CUSTOMER_ORG, user_id=user_id, role="admin", status="active"))
        session.add(UserRow(id="zz-selected", email="selected@example.test", password_hash=None, system_role="user", needs_setup=False, token_version=0, created_at=now))
        session.add(OrganizationMemberRow(organization_id=CUSTOMER_ORG, user_id="zz-selected", role="admin", status="active"))
    w.script = [("read_client_work_plan", {})]
    async with _http(w.app) as client:
        request_id, record = await _start(w, client)
        model_first = w.results[0]["participants"]
        assert model_first["limit"] == 50 and len(model_first["items"]) == 50 and model_first["has_more"]
        assert model_first["next_cursor"] and len(model_first["next_cursor"]) <= 512
        payload = _work_plan(assignee_user_id="zz-selected", verifier_user_id=USER_C)
        saved = await client.put(f"{BASE}/{request_id}/work-plan", headers=auth_headers(USER_C, CUSTOMER_ORG), json=payload)
        assert saved.status_code == 200, saved.text
        path = f"{BASE}/{request_id}/work-plan/participants"
        first = await client.get(path, headers=auth_headers(USER_C, CUSTOMER_ORG), params={"limit": 100})
        assert first.status_code == 200, first.text
        first_page = first.json()
        assert first_page["limit"] == 100 and len(first_page["items"]) == 100 and first_page["has_more"]
        first_ids = [item["user_id"] for item in first_page["items"]]
        assert "zz-selected" not in first_ids
        assert first_page["selected_items"] == [
            {"user_id": USER_C, "email": "user-c@example.com", "role": "account_manager"},
            {"user_id": "zz-selected", "email": "selected@example.test", "role": "admin"},
        ]
        second = await client.get(path, headers=auth_headers(USER_C, CUSTOMER_ORG), params={"limit": 100, "cursor": first_page["next_cursor"]})
        assert second.status_code == 200, second.text
        second_page = second.json()
        all_ids = first_ids + [item["user_id"] for item in second_page["items"]]
        assert len(all_ids) == 107 and all_ids == sorted(all_ids) and len(set(all_ids)) == len(all_ids)
        assert not second_page["has_more"] and second_page["next_cursor"] is None
        default = await client.get(path, headers=auth_headers(USER_C, CUSTOMER_ORG))
        assert default.status_code == 200 and default.json()["limit"] == 50 and len(default.json()["items"]) == 50
        assert default.json()["next_cursor"] and len(default.json()["next_cursor"]) <= 512
        malformed = await client.get(path, headers=auth_headers(USER_C, CUSTOMER_ORG), params={"cursor": "not opaque"})
        assert malformed.status_code == 422 and malformed.json()["detail"] == "Invalid work-plan participant cursor"
        assert "not opaque" not in malformed.text
        too_large = await client.get(path, headers=auth_headers(USER_C, CUSTOMER_ORG), params={"limit": 101})
        assert too_large.status_code == 422
        record_only = await client.get(f"{BASE}/{request_id}/work-plan", headers=auth_headers(USER_C, CUSTOMER_ORG))
        assert record_only.status_code == 200 and record_only.json()["plan"] == saved.json()["plan"]
        direct = json.loads(await read_client_work_plan.coroutine(_runtime(w.capabilities[0]), model_first["next_cursor"]))
        assert direct["plan"] == saved.json()["plan"]
        _, tool_results = await _run_tool_commands(w, client, record.thread_id, [("read_client_work_plan", {"participants_cursor": model_first["next_cursor"]})])
        resumed_direct = json.loads(await read_client_work_plan.coroutine(_runtime(w.capabilities[-1]), model_first["next_cursor"]))
        assert resumed_direct["plan"] == saved.json()["plan"], {"resumed_direct": resumed_direct, "request_id": request_id, "capability": w.capabilities[-1]}
        tool_page = tool_results[0]["participants"]
        assert w.capabilities[-1].request_id == request_id and tool_page["source"]["thread_id"] == request_id
        assert tool_results[0]["plan"] == saved.json()["plan"], {"result": tool_results[0], "request_id": request_id, "capability_request_id": w.capabilities[-1].request_id}
        assert len(tool_page["items"]) == 50 and tool_page["has_more"]
        assert {item["user_id"] for item in tool_page["selected_items"]} == {USER_C, "zz-selected"}, tool_results[0]
        assert "selected@example.test" in json.dumps(tool_page["selected_items"])
        assert record_only.status_code == 200 and "participants" not in record_only.json() and "current_actor_user_id" not in record_only.json()
        other = await client.post(BASE, headers=auth_headers(USER_B, CUSTOMER_ORG), json={"client_id": "client-a", "submission_key": "participant-cursor-other", "subject": "Other request", "body": "Synthetic request"})
        assert other.status_code == 200, other.text
        foreign = await client.get(f"{BASE}/{other.json()['id']}/work-plan/participants", headers=auth_headers(USER_C, CUSTOMER_ORG), params={"limit": 100, "cursor": first_page["next_cursor"]})
        assert foreign.status_code == 422 and foreign.json()["detail"] == "Invalid work-plan participant cursor"
        assert first_page["next_cursor"] not in foreign.text


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
    assert set(read_client_work_plan.tool_call_schema.model_fields) == {"participants_cursor"}
    assert read_client_work_plan.tool_call_schema.model_fields["participants_cursor"].default is None
    assert set(update_client_work_plan.tool_call_schema.model_fields) == {"expected_revision", "plan"}
    with pytest.raises(ValidationError):
        read_client_work_plan.args_schema.model_validate({"actor_id": USER_A})
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
