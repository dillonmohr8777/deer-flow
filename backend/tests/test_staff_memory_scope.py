"""Synthetic staff isolation; no existing memory, auth config, or provider I/O."""

import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph.message import add_messages
from langgraph.runtime import Runtime
from org_isolation_fixtures import ORG_S, auth_headers, org_world  # noqa: F401
from test_client_portal import BASE, CUSTOMER_ORG, USER_A, USER_B, USER_C, _compose, _http, project_work_world, world  # noqa: F401

from deerflow.agents.memory.scope import STAFF_MEMORY_SCOPE_KEY, resolve_memory_scope, staff_memory_scope
from deerflow.agents.middlewares import dynamic_context_middleware as dynamic
from deerflow.agents.middlewares import memory_middleware as capture
from deerflow.config.memory_config import MemoryConfig
from deerflow.runtime.context_keys import CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY
from deerflow.runtime.user_context import AUTHENTICATED_CONTEXT_MARKER, AUTHENTICATED_CONTEXT_MARKER_KEY

pytestmark = pytest.mark.no_auto_user


@pytest.fixture(autouse=True)
def _synthetic_momo_api_mode(monkeypatch):
    monkeypatch.setattr("app.gateway.routers.memory._momo_memory_enabled", lambda: True)


class Memory:
    """An intentionally user-global summary/cache, like DeerMem's manifest."""

    def __init__(self):
        self.values = {}
        self.cache = {}
        self.writes = []

    def get_context(self, *, user_id, agent_name, **_):
        return self.cache.setdefault(user_id, self.values.get(user_id, ""))

    def add(self, thread_id, messages, *, user_id, agent_name, **_):
        text = " ".join(m.content for m in messages if isinstance(m, (HumanMessage, AIMessage)) and not m.additional_kwargs.get("hide_from_ui"))
        self.values[user_id] = text
        self.cache.pop(user_id, None)
        self.writes.append((user_id, text))

    async def aadd(self, *args, **kwargs):
        self.add(*args, **kwargs)

    def add_nowait(self, *args, **kwargs):
        self.add(*args, **kwargs)


def runtime(actor="am-a", client=None, agent="momobot-max", role="user", storage="agency", org="org-a"):
    context = {
        AUTHENTICATED_CONTEXT_MARKER_KEY: AUTHENTICATED_CONTEXT_MARKER,
        "actor_user_id": actor,
        "storage_user_id": storage,
        "organization_id": org,
        "organization_role": "member",
        "user_role": role,
    }
    scope = staff_memory_scope(context, agent_name=agent, client_id=client)
    return Runtime(context={"thread_id": "same-thread", "agent_name": agent, "user_role": role, STAFF_MEMORY_SCOPE_KEY: scope})


@pytest.fixture
def memory(monkeypatch):
    from deerflow.agents import memory as memory_module

    manager = Memory()
    monkeypatch.setattr(memory_module, "get_memory_manager", lambda: manager)
    monkeypatch.setattr(capture, "get_memory_manager", lambda: manager)
    return manager


def run(messages, rt, *, agent="momobot-max"):
    middleware = dynamic.DynamicContextMiddleware(agent, app_config=SimpleNamespace(memory=MemoryConfig(enabled=True)))
    update = middleware.before_agent({"messages": messages}, rt)
    return add_messages(messages, update["messages"]) if update else messages


def test_global_summary_and_capture_are_private_per_actor_client_agent_role(memory):
    variants = [
        runtime(),
        runtime(client="A"),
        runtime(client="B"),
        runtime("am-b", "A"),
        runtime(client="A", agent="researcher"),
        runtime(client="A", role="exec"),
        runtime(client="A", storage="other-workspace"),
        runtime(client="A", org="org-b"),
    ]
    for index, rt in enumerate(variants):
        agent = rt.context["agent_name"]
        sentinel = f"SENTINEL_{index}"
        messages = run([HumanMessage(id=f"u{index}", content=sentinel)], rt, agent=agent)
        capture.MemoryMiddleware(agent, memory_config=MemoryConfig()).after_agent({"messages": messages + [AIMessage(content="Saved")]}, rt)
    assert len(memory.values) == len(variants)
    for index, rt in enumerate(variants):
        agent = rt.context["agent_name"]
        messages = run([HumanMessage(id=f"next{index}", content="Recall")], rt, agent=agent)
        blocks = [m.content for m in messages if m.id.endswith("__memory")]
        assert len(blocks) == 1 and f"SENTINEL_{index}" in blocks[0]
        assert all(f"SENTINEL_{other}" not in blocks[0] for other in range(len(variants)) if other != index)


def test_same_thread_same_day_replaces_foreign_and_legacy_injection_without_recapture(memory):
    a, b = runtime(client="A"), runtime(client="B")
    a_scope, b_scope = resolve_memory_scope(a, "momobot-max"), resolve_memory_scope(b, "momobot-max")
    memory.values[a_scope.user_id] = "A_PRIVATE"
    memory.values[b_scope.user_id] = "B_PRIVATE"
    messages = run([HumanMessage(id="first", content="A transcript")], a)
    messages += [AIMessage(id="answer", content="A answer"), HumanMessage(id="second", content="B transcript")]
    b.context[CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY] = frozenset(m.id for m in messages[:-1])
    messages = run(messages, b)
    blocks = [m.content for m in messages if m.id.endswith("__memory")]
    assert len(blocks) == 1 and "B_PRIVATE" in blocks[0] and "A_PRIVATE" not in blocks[0]
    capture.MemoryMiddleware("momobot-max", memory_config=MemoryConfig()).after_agent({"messages": messages + [AIMessage(content="B answer")]}, b)
    assert "B transcript" in memory.values[b_scope.user_id]
    assert "A transcript" not in memory.values[b_scope.user_id]
    for m in messages:
        if m.id.endswith("__memory"):
            m.additional_kwargs.pop("deerflow_memory_scope", None)
    messages.append(HumanMessage(id="third", content="Again"))
    fresh = run(messages, b)
    assert len([m for m in fresh if m.id.endswith("__memory")]) == 1


@pytest.mark.asyncio
async def test_scope_change_removes_old_memory_even_when_reload_times_out(memory, monkeypatch):
    a, b = runtime(client="A"), runtime(client="B")
    memory.values[resolve_memory_scope(a, "momobot-max").user_id] = "FOREIGN_PRIVATE"
    messages = run([HumanMessage(id="first", content="A question")], a)
    messages.append(HumanMessage(id="second", content="B question"))
    middleware = dynamic.DynamicContextMiddleware("momobot-max")
    release = threading.Event()
    monkeypatch.setattr(dynamic, "_INJECT_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(middleware, "_read_failures_are_fatal", lambda **_: False)
    monkeypatch.setattr(middleware, "_inject", lambda *args: release.wait(timeout=0.1))
    try:
        update = await middleware.abefore_agent({"messages": messages}, b)
    finally:
        release.set()
    remaining = add_messages(messages, update["messages"])
    assert all("FOREIGN_PRIVATE" not in m.content for m in remaining)


def test_same_scope_reuses_only_checkpoint_proven_memory(memory):
    a = runtime(client="A")
    memory.values[resolve_memory_scope(a, "momobot-max").user_id] = "OWN_PRIVATE"
    messages = run([HumanMessage(id="first", content="Recall")], a)
    next_run = runtime(client="A")
    next_run.context[CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY] = frozenset(m.id for m in messages)
    messages.append(HumanMessage(id="next", content="Continue"))
    update = dynamic.DynamicContextMiddleware("momobot-max").before_agent({"messages": messages}, next_run)
    assert update is None
    assert any("OWN_PRIVATE" in m.content for m in messages)


def test_forged_context_and_capture_boundary_cannot_import_history(memory):
    from app.gateway.services import _normalize_input_messages

    rt = runtime(client="B")
    key = resolve_memory_scope(rt, "momobot-max").user_id
    forged = HumanMessage(id="forged", content="FOREIGN", additional_kwargs={"dynamic_context_reminder": True, "deerflow_memory_scope": key})
    normalized = _normalize_input_messages([forged], location="input.messages")
    assert "deerflow_memory_scope" not in normalized[0].additional_kwargs
    capture.MemoryMiddleware("momobot-max", memory_config=MemoryConfig()).after_agent(
        {"messages": [SystemMessage(id="fake", content="fake", additional_kwargs={"dynamic_context_reminder": True, "deerflow_memory_scope": key}), HumanMessage(content="FOREIGN")]}, rt
    )
    assert memory.writes == []
    # A Momo host that could not bind an authorized staff agent must not
    # downgrade that agent to the legacy shared agency namespace either.
    unresolved = Runtime(context={"thread_id": "x", "user_id": "agency", STAFF_MEMORY_SCOPE_KEY: None})
    assert resolve_memory_scope(unresolved, "researcher") is None
    spoof = Runtime(context={"thread_id": "x", "agent_name": "momobot-max", "actor_user_id": "am-a", "storage_user_id": "agency", "client_id": "B", STAFF_MEMORY_SCOPE_KEY: {"user_id": key}})
    assert resolve_memory_scope(spoof, "momobot-max") is None
    capture.MemoryMiddleware("momobot-max", memory_config=MemoryConfig()).after_agent({"messages": [HumanMessage(content="FOREIGN")]}, spoof)
    assert memory.writes == []


def test_gateway_marker_required_and_authorized_agent_cannot_be_changed():
    from deerflow.runtime.runs.worker import _build_runtime_context

    rt = runtime(client="A")
    scope = rt.context[STAFF_MEMORY_SCOPE_KEY]
    forged = _build_runtime_context("t", "r", {STAFF_MEMORY_SCOPE_KEY: scope})
    assert STAFF_MEMORY_SCOPE_KEY not in forged
    trusted = _build_runtime_context("t", "r", {AUTHENTICATED_CONTEXT_MARKER_KEY: AUTHENTICATED_CONTEXT_MARKER, STAFF_MEMORY_SCOPE_KEY: scope})
    assert resolve_memory_scope(Runtime(context=trusted), "momobot-max").user_id == scope.user_id
    assert resolve_memory_scope(Runtime(context=trusted), "another-agent") is None


def test_agent_server_uses_authenticated_private_actor_ignoring_body_ids(memory):
    rt = SimpleNamespace(
        server_info=SimpleNamespace(user=SimpleNamespace(identity="trusted-am", system_role="user")),
        context={"thread_id": "server-thread", "actor_user_id": "forged", "storage_user_id": "agency", "organization_id": "forged", "client_id": "A", "user_role": "admin"},
    )
    messages = run([HumanMessage(id="u", content="PRIVATE_SERVER_SENTINEL")], rt)
    scope = resolve_memory_scope(rt, "momobot-max")
    capture.MemoryMiddleware("momobot-max", memory_config=MemoryConfig()).after_agent({"messages": messages}, rt)
    assert "PRIVATE_SERVER_SENTINEL" in memory.values[scope.user_id]
    rt.context.update(actor_user_id="another-forgery", client_id="B")
    assert resolve_memory_scope(rt, "momobot-max").user_id == scope.user_id
    # Agent Server has no Gateway checkpoint-ID capability: reload rather than
    # treating a persisted hash as proof, without accumulating hidden blocks.
    fresh_rt = SimpleNamespace(server_info=rt.server_info, context={"thread_id": "server-thread"})
    memory.values[scope.user_id] = "UPDATED_PRIVATE"
    memory.cache.clear()
    messages.append(HumanMessage(id="again", content="Recall"))
    refreshed = run(messages, fresh_rt)
    assert len([m for m in refreshed if m.id.endswith("__memory")]) == 1
    assert any("UPDATED_PRIVATE" in m.content for m in refreshed)
    rt.server_info.user = SimpleNamespace(identity="another-authenticated-actor", system_role="user")
    assert resolve_memory_scope(rt, "momobot-max") is None
    unknown_role = SimpleNamespace(server_info=SimpleNamespace(user=SimpleNamespace(identity="trusted-am")), context={"user_role": "user"})
    assert resolve_memory_scope(unknown_role, "momobot-max") is None


def test_client_and_agent_opt_out_remove_old_memory_without_read_or_capture(memory):
    client = runtime(role="client")
    old = HumanMessage(id="old__memory", content="LEGACY", additional_kwargs={"dynamic_context_reminder": True})
    messages = run([old, HumanMessage(id="new", content="Hi")], client)
    assert all(m.content != "LEGACY" for m in messages)
    capture.MemoryMiddleware("momobot-max", memory_config=MemoryConfig()).after_agent({"messages": messages}, client)
    assert not memory.values and not memory.writes
    scoped = runtime()
    middleware = dynamic.DynamicContextMiddleware("momobot-max", memory_enabled=False)
    update = middleware.before_agent({"messages": [old, HumanMessage(id="u", content="Hi")]}, scoped)
    assert any(m.type == "remove" and m.id == old.id for m in update["messages"])


def test_http_memory_is_private_and_cannot_select_legacy_or_bound_client(memory):
    from app.gateway.routers import memory as api
    from deerflow.runtime.user_context import WorkspaceStorageContext, reset_current_user, reset_storage_context, set_current_user, set_storage_context

    for actor in ("am-a", "am-b"):
        user = SimpleNamespace(id=actor, system_role="user")
        user_token = set_current_user(user)
        workspace_token = set_storage_context(WorkspaceStorageContext(actor, "org-a", "agency", "member"))
        try:
            request = SimpleNamespace(state=SimpleNamespace(user=user, auth_source="session"), query_params={"client_id": "A", "user_id": "agency"}, headers={})
            key = api._resolve_memory_user_id(request)
            assert key == resolve_memory_scope(runtime(actor), "momobot-max").user_id
            memory.values[key] = actor
        finally:
            reset_storage_context(workspace_token)
            reset_current_user(user_token)
    assert len(memory.values) == 2 and "agency" not in memory.values


@pytest.mark.asyncio
async def test_real_gateway_bound_client_isolates_two_assigned_staff(project_work_world, memory):  # noqa: F811
    """Real portal/SQL admission supplies the namespace, despite forged IDs."""
    from deerflow.persistence.clients.model import ClientAssignmentRow
    from deerflow.persistence.organizations.model import OrganizationMemberRow
    from deerflow.runtime.runs.worker import _build_runtime_context

    w = project_work_world
    async with w.sf() as session, session.begin():
        membership = await session.get(OrganizationMemberRow, (CUSTOMER_ORG, USER_A))
        membership.role = "member"
        session.add(ClientAssignmentRow(client_id="client-a", user_id=USER_A, organization_id=ORG_S, role="account_manager"))
    async with _http(w.app) as client:
        created = await _compose(client, auth_headers(USER_B, CUSTOMER_ORG))
        first = await client.post(f"{BASE}/{created['id']}/work", headers=auth_headers(USER_C, CUSTOMER_ORG), json={"project_id": "project-a"})
        assert first.status_code == 200, first.text
        record = w.app.state.run_manager._runs[first.json()["run_id"]]
        if record.task:
            await record.task
        first_config = w.project_calls[-1]["config"]
        rt_a = Runtime(context=_build_runtime_context(record.thread_id, record.run_id, first_config["context"]))
        messages = run([HumanMessage(id="staff-a", content="STAFF_A_PRIVATE_SENTINEL")], rt_a)
        capture.MemoryMiddleware("momobot-max", memory_config=MemoryConfig()).after_agent({"messages": messages + [AIMessage(content="Saved")]}, rt_a)
        body = {
            "assistant_id": "momobot-max",
            "input": {"messages": [{"role": "user", "content": "Recall my client context"}]},
            "context": {"client_id": "client-b", "actor_user_id": USER_C, "storage_user_id": "forged-workspace"},
            "config": {"context": {"client_id": "client-b"}, "configurable": {"actor_user_id": USER_C}},
        }
        second = await client.post(f"/api/threads/{record.thread_id}/runs", headers=auth_headers(USER_A, CUSTOMER_ORG), json=body)
        assert second.status_code == 200, second.text
        second_record = w.app.state.run_manager._runs[second.json()["run_id"]]
        if second_record.task:
            await second_record.task
        config = w.project_calls[-1]["config"]
        rt_b = Runtime(context=_build_runtime_context(record.thread_id, second_record.run_id, config["context"]))
        rendered = "\n".join(m.content for m in run([HumanMessage(id="staff-b", content="Recall")], rt_b))
        assert "STAFF_A_PRIVATE_SENTINEL" not in rendered
        assert STAFF_MEMORY_SCOPE_KEY not in str(second_record.kwargs)


def test_scoped_key_never_replaces_provider_or_workspace_identity(tmp_path, monkeypatch, memory):
    from deerflow.agents.memory.backends.deermem.deer_mem import DeerMem
    from deerflow.runtime.user_context import WorkspaceStorageContext, get_current_user, get_storage_context, reset_current_user, reset_storage_context, set_current_user, set_storage_context

    seen = []
    user = SimpleNamespace(id="am-a", system_role="user")
    workspace = WorkspaceStorageContext("am-a", "org-a", "agency", "member")
    user_token, storage_token = set_current_user(user), set_storage_context(workspace)
    try:

        def factory():
            seen.append(("model", get_current_user().id, get_storage_context().storage_user_id))
            return MagicMock()

        manager = DeerMem.from_config({"storage_path": str(tmp_path), "token_counting": "char"}, host_llm_factory=factory)
        monkeypatch.setattr(manager._queue, "add", lambda **kwargs: seen.append(("queue", get_current_user().id, get_storage_context().storage_user_id, kwargs["user_id"])))
        monkeypatch.setattr(capture, "get_memory_manager", lambda: manager)
        rt = runtime(client="A")
        # The host factory is built once, independently of the per-write storage key.
        messages = run([HumanMessage(id="provider", content="A useful synthetic preference")], rt)
        capture.MemoryMiddleware("momobot-max", memory_config=MemoryConfig()).after_agent({"messages": messages + [AIMessage(content="Saved")]}, rt)
        assert seen[0] == ("model", "am-a", "agency")
        assert seen[1] == ("queue", "am-a", "agency", resolve_memory_scope(rt, "momobot-max").user_id)
        assert get_current_user() is user and get_storage_context() is workspace
    finally:
        reset_storage_context(storage_token)
        reset_current_user(user_token)


@pytest.mark.asyncio
async def test_verified_delegated_owner_can_read_write_and_clear_private_scope(monkeypatch):
    from app.gateway.routers import memory as api
    from deerflow.runtime.user_context import WorkspaceStorageContext, reset_current_user, reset_storage_context, set_current_user, set_storage_context

    user = SimpleNamespace(id="am-a", system_role="internal")
    user_token = set_current_user(user)
    storage_token = set_storage_context(WorkspaceStorageContext("am-a", "org-a", "agency", "member"))
    request = SimpleNamespace(state=SimpleNamespace(user=user, auth_source="internal", delegation_id="verified", actor_user_id="am-a", storage_user_id="agency"), headers={})
    owner = SimpleNamespace(id="am-a", system_role="user")
    monkeypatch.setattr("app.gateway.services.resolve_trusted_internal_owner_for_attribution", AsyncMock(return_value=owner))
    manager = MagicMock()
    manager.get_memory.return_value = {}
    manager.create_fact.return_value = ({}, "new-fact")
    manager.clear_memory.return_value = {}
    monkeypatch.setattr(api, "get_memory_manager", lambda: manager)
    try:
        await api._staff_memory_only(request)
        expected = request.state.staff_memory_scope.user_id
        await api.get_memory(request)
        await api.create_memory_fact_endpoint(api.FactCreateRequest(content="Delegated private fact"), request)
        await api.clear_memory(request)
        assert all(call.kwargs["user_id"] == expected and call.kwargs["agent_name"] == "momobot-max" for call in (manager.get_memory.call_args, manager.create_fact.call_args, manager.clear_memory.call_args))
        assert expected != "agency"
    finally:
        reset_storage_context(storage_token)
        reset_current_user(user_token)


def test_max_sdk_management_uses_verified_private_scope_for_every_operation(monkeypatch):
    from deerflow.client import DeerFlowClient
    from deerflow.runtime.user_context import WorkspaceStorageContext, reset_current_user, reset_storage_context, set_current_user, set_storage_context

    sdk = object.__new__(DeerFlowClient)
    sdk._agent_name = "momobot-max"
    sdk.user_id = "forged-namespace"
    manager = MagicMock()
    manager.create_fact.return_value = ({}, "created")
    manager.reload_memory.side_effect = NotImplementedError
    get_manager = MagicMock(return_value=manager)
    monkeypatch.setattr("deerflow.agents.memory.get_memory_manager", get_manager)
    operations = [
        sdk.get_memory,
        sdk.export_memory,
        lambda: sdk.import_memory({}),
        sdk.reload_memory,
        sdk.clear_memory,
        lambda: sdk.create_memory_fact("Owned fact"),
        lambda: sdk.update_memory_fact("fact", content="Updated"),
        lambda: sdk.delete_memory_fact("fact"),
    ]
    for operation in operations:
        with pytest.raises(PermissionError):
            operation()
    get_manager.assert_not_called()
    user_token = set_current_user(SimpleNamespace(id="am-a", system_role="user"))
    storage_token = set_storage_context(WorkspaceStorageContext("am-a", "org-a", "agency", "member"))
    try:
        expected = resolve_memory_scope(runtime(), "momobot-max").user_id
        for operation in operations:
            operation()
        assert len(manager.method_calls) == 9  # reload's unsupported fallback is also scoped.
        assert all(call.kwargs["user_id"] == expected and call.kwargs["agent_name"] == "momobot-max" for call in manager.method_calls)
    finally:
        reset_storage_context(storage_token)
        reset_current_user(user_token)


def test_generic_http_and_sdk_keep_existing_non_momo_scope(monkeypatch):
    from app.gateway.routers import memory as api
    from deerflow.client import DeerFlowClient

    monkeypatch.setattr(api, "_momo_memory_enabled", lambda: False)
    monkeypatch.setattr(api, "get_effective_user_id", lambda: "generic-workspace")
    request = SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(id="generic-user", system_role="user")), headers={})
    assert api._memory_scope_args(request) == {"user_id": "generic-workspace"}
    sdk = object.__new__(DeerFlowClient)
    sdk._agent_name = "researcher"
    monkeypatch.setattr("deerflow.client.get_effective_user_id", lambda: "generic-workspace")
    assert sdk._memory_scope_args() == {"user_id": "generic-workspace"}
