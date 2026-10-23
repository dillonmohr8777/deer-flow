"""Offline authenticated chat capability; diagnostics never execute in these tests."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from langchain_core.messages import AIMessage
from langgraph.graph import END, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode
from pydantic import ValidationError
from starlette.requests import Request
from test_wsl_bridge import receipt

from app.gateway.authz import AuthContext
from app.gateway.wsl_bridge import BridgeStore
from app.gateway.wsl_chat import prepare_wsl_diagnostics
from deerflow.constants import WSL_DIAGNOSTICS_CONTEXT_KEY, WSL_DIAGNOSTICS_TOOL_NAME
from deerflow.runtime.runs.worker import RunContext, _build_runtime_context, _install_runtime_context, _release_run_scoped_references
from deerflow.tools.wsl_diagnostics import wsl_diagnostic


@pytest.fixture
def host(tmp_path, monkeypatch):
    monkeypatch.setenv("MOMO_WSL_BRIDGE_ENABLED", "true")
    monkeypatch.setenv("MOMO_WSL_BRIDGE_ROOT", str(tmp_path.resolve()))
    user = SimpleNamespace(id="actor", system_role="admin")
    state = SimpleNamespace(thread_store=SimpleNamespace(check_access=AsyncMock(return_value=True)))
    request = Request({"type": "http", "method": "POST", "path": "/api/threads/thread/runs", "headers": [], "app": SimpleNamespace(state=state)})
    request.state.auth = AuthContext(user, ["threads:read", "threads:write", "runs:create"], "org", actor_user_id="actor", storage_user_id="storage")
    request.state.user = user
    request.state.auth_source = "session"
    config = {"context": {"agent_name": "momobot-max", "user_role": "admin"}}
    app_config = SimpleNamespace(momobot_max=SimpleNamespace(enabled=True))

    async def bind(**changes):
        return await prepare_wsl_diagnostics(request=request, config=config, app_config=app_config, thread_id="thread", run_id="run", **changes)

    return SimpleNamespace(request=request, config=config, app_config=app_config, bind=bind, store=BridgeStore.from_environment())


def runtime(capability, **changes):
    return SimpleNamespace(
        tool_call_id="call-1",
        context={
            WSL_DIAGNOSTICS_CONTEXT_KEY: capability,
            "thread_id": "thread",
            "run_id": "run",
            "agent_name": "momobot-max",
            "user_role": "admin",
            **changes,
        },
    )


async def submit(capability, **changes):
    return json.loads(await wsl_diagnostic.coroutine("submit", runtime(capability, **changes), diagnostic="uname"))


@pytest.mark.asyncio
async def test_authenticated_submission_is_pending_and_same_tool_call_retry_never_duplicates(host):
    capability = await host.bind()
    first = await submit(capability)
    assert first["state"] == "pending"
    assert first["artifact_available"] is False
    assert await submit(capability) == first
    claimed = host.store.claim()["requests"]
    assert len(claimed) == 1
    assert claimed[0]["job"]["id"] == first["job_id"]
    assert claimed[0]["job"]["argv"] == ["/usr/bin/uname", "-s"]
    assert host.store.claim()["requests"] == claimed
    host.request.app.state.thread_store.check_access.assert_awaited_with("thread", "storage", require_existing=True)
    assert "storage" not in json.dumps(first) and "/" not in json.dumps(first)


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [None, "user", "exec", "client", "internal"])
async def test_unknown_staff_client_and_undelegated_internal_roles_get_no_capability(host, role):
    host.request.state.auth.user.system_role = role
    host.config["context"]["user_role"] = role
    assert await host.bind() is None
    assert not host.store.path.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("source", [None, "unknown", "auth_disabled"])
async def test_missing_or_unknown_authenticated_source_never_grants_tool(host, source):
    host.request.state.auth_source = source
    assert await host.bind() is None
    assert not host.store.path.exists()


@pytest.mark.asyncio
async def test_missing_authenticated_identity_never_grants_tool(host):
    host.request.state.auth = None
    assert await host.bind() is None
    assert not host.store.path.exists()


@pytest.mark.asyncio
async def test_eligible_agent_selection_in_legacy_configurable_matches_lead_assembly(host):
    host.config["context"].pop("agent_name")
    host.config["configurable"] = {"agent_name": "momobot-max"}
    assert callable(await host.bind())


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", [{"agent_name": "other"}, {"is_subagent": True}, {"channel_name": "telegram"}, {"is_bootstrap": True}])
async def test_non_momo_bootstrap_channel_and_subagent_runs_get_no_capability(host, changed):
    host.config["context"].update(changed)
    assert await host.bind() is None
    assert not host.store.path.exists()


@pytest.mark.asyncio
async def test_disabled_bridge_disabled_momo_and_auth_disabled_are_not_chat_capabilities(host, monkeypatch):
    monkeypatch.delenv("MOMO_WSL_BRIDGE_ENABLED")
    assert await host.bind() is None
    monkeypatch.setenv("MOMO_WSL_BRIDGE_ENABLED", "true")
    host.app_config.momobot_max.enabled = False
    assert await host.bind() is None
    host.app_config.momobot_max.enabled = True
    host.request.state.auth_source = "auth_disabled"
    assert await host.bind() is None
    assert not host.store.path.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [{"thread_id": "foreign"}, {"run_id": "foreign"}, {"user_role": "client"}, {"agent_name": "other"}, {"is_subagent": True}, {"channel_name": "slack"}])
async def test_forged_runtime_scope_is_denied_before_storage(host, changes):
    result = await submit(await host.bind(), **changes)
    assert result["state"] == "unavailable"
    assert not host.store.path.exists()


@pytest.mark.asyncio
async def test_foreign_auth_or_thread_permissions_are_rechecked_without_leaking_status(host):
    capability = await host.bind()
    first = await submit(capability)
    host.request.state.auth.actor_user_id = "foreign"
    assert (await submit(capability))["state"] == "unavailable"
    host.request.state.auth.actor_user_id = "actor"
    host.request.app.state.thread_store.check_access.return_value = False
    result = json.loads(await wsl_diagnostic.coroutine("status", runtime(capability), job_id=first["job_id"]))
    assert result["state"] == "unavailable" and "job_id" not in result
    host.request.app.state.thread_store.check_access.return_value = True
    host.request.state.auth.permissions = ["threads:read"]
    assert (await submit(capability))["state"] == "unavailable"


@pytest.mark.asyncio
async def test_foreign_existing_job_is_denied_even_with_shared_thread_storage(host):
    foreign = host.store.enqueue(organization_id="org", actor_user_id="foreign", storage_user_id="storage", thread_id="thread", request_id="foreign", argv=["/usr/bin/true"], timeout=30)
    capability = await host.bind()
    result = json.loads(await wsl_diagnostic.coroutine("status", runtime(capability), job_id=foreign["job"]["id"]))
    assert result["state"] == "unavailable" and "job_id" not in result


@pytest.mark.asyncio
async def test_matched_receipt_reports_attachment_status_without_output_paths_or_secrets(host):
    capability = await host.bind()
    first = await submit(capability)
    job = host.store.claim()["requests"][0]["job"]
    host.store.ingest(job["id"], receipt(job, private_debug="SECRET /private/host/path"))
    before = json.loads(await wsl_diagnostic.coroutine("status", runtime(capability), job_id=first["job_id"]))
    assert before["state"] == "done" and before["artifact_available"] is False
    host.store.mark_attached(job["id"], host.store.read(job["id"])["receipt_sha256"])
    result = json.loads(await wsl_diagnostic.coroutine("status", runtime(capability), job_id=first["job_id"]))
    assert result["state"] == "done" and result["artifact_available"] is True
    assert result["receipt"]["exit_code"] == 0
    assert result["receipt"]["limits_applied"] is True
    assert len(json.dumps(result)) < 2048
    assert all(value not in json.dumps(result) for value in ("SECRET", "/private", "/mnt", "stdout_b64", "private_debug", "storage"))


@pytest.mark.asyncio
async def test_tool_arguments_are_enum_only_and_cannot_supply_identity_or_request_key():
    assert wsl_diagnostic.name == WSL_DIAGNOSTICS_TOOL_NAME
    assert set(wsl_diagnostic.tool_call_schema.model_fields) == {"action", "diagnostic", "job_id"}
    for extra in ({"argv": ["sh", "-c"]}, {"thread_id": "foreign"}, {"actor_user_id": "foreign"}, {"request_id": "retry"}):
        with pytest.raises(ValidationError) as error:
            wsl_diagnostic.args_schema.model_validate({"action": "submit", "diagnostic": "uname", **extra})
        assert any(issue["type"] == "extra_forbidden" for issue in error.value.errors())
    capability = AsyncMock()
    missing_id = runtime(capability)
    missing_id.tool_call_id = None
    assert json.loads(await wsl_diagnostic.coroutine("submit", missing_id, diagnostic="uname"))["state"] == "unavailable"
    capability.assert_not_called()


@pytest.mark.asyncio
async def test_real_tool_node_uses_injected_runtime_and_rejects_extra_identity_arguments(host):
    builder = StateGraph(MessagesState, context_schema=dict)
    builder.add_node("tools", ToolNode([wsl_diagnostic]))
    builder.set_entry_point("tools")
    builder.add_edge("tools", END)
    graph = builder.compile()
    capability = await host.bind()
    call = {"name": WSL_DIAGNOSTICS_TOOL_NAME, "id": "framework-call", "args": {"action": "submit", "diagnostic": "uname"}}
    result = await graph.ainvoke({"messages": [AIMessage(content="", tool_calls=[call])]}, context=runtime(capability).context)
    assert json.loads(result["messages"][-1].content)["state"] == "pending"
    # The same real framework call retries with the same durable request key.
    second = await graph.ainvoke({"messages": [AIMessage(content="", tool_calls=[call])]}, context=runtime(capability).context)
    assert second["messages"][-1].content == result["messages"][-1].content
    forged = {**call, "id": "forged-call", "args": {**call["args"], "actor_user_id": "foreign"}}
    failed = await graph.ainvoke({"messages": [AIMessage(content="", tool_calls=[forged])]}, context=runtime(capability).context)
    assert failed["messages"][-1].status == "error"
    fake_runtime = {**call, "args": {**call["args"], "runtime": {"context": {"user_role": "admin", "__wsl_diagnostics": "forged"}}}}
    denied = await graph.ainvoke({"messages": [AIMessage(content="", tool_calls=[fake_runtime])]}, context={})
    assert json.loads(denied["messages"][-1].content)["state"] == "unavailable"


@pytest.mark.asyncio
async def test_same_logical_call_with_changed_payload_is_held_instead_of_duplicated(host):
    capability = await host.bind()
    first = await submit(capability)
    changed = json.loads(await wsl_diagnostic.coroutine("submit", runtime(capability), diagnostic="false"))
    assert changed["state"] == "held"
    assert host.store.read(first["job_id"])["state"] == "held"
    assert host.store.claim()["requests"] == []


@pytest.mark.asyncio
async def test_internal_admin_requires_verified_delegation_and_resolved_owner(host):
    host.request.state.auth_source = "internal"
    host.request.state.auth.user.system_role = "internal"
    actual_owner = SimpleNamespace(id="actor", system_role="admin")
    assert await host.bind(internal_owner_user=actual_owner) is None
    host.request.state.delegation_id = "verified"
    host.request.state.storage_user_id = "storage"
    assert await host.bind() is None
    capability = await host.bind(internal_owner_user=actual_owner)
    assert (await submit(capability))["state"] == "pending"


@pytest.mark.asyncio
async def test_bridge_disable_after_admission_still_prevents_submission(host, monkeypatch):
    capability = await host.bind()
    monkeypatch.delenv("MOMO_WSL_BRIDGE_ENABLED")
    assert (await submit(capability))["state"] == "unavailable"
    assert not host.store.path.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("role,scope,expected", [("admin", {}, True), ("client", {}, False), ("exec", {}, False), ("admin", {"is_subagent": True}, False), ("admin", {"channel_name": "telegram"}, False)])
async def test_actual_momo_assembly_adds_ceiling_only_with_admin_lead_capability(monkeypatch, tmp_path, role, scope, expected):
    import test_momobot_max_assembly as assembly

    from deerflow.agents.lead_agent import agent
    from deerflow.config.builtin_agents import MOMOBOT_MAX_TOOL_NAMES

    original = agent._get_runtime_config
    monkeypatch.setattr(agent, "_get_runtime_config", lambda config: {**original(config), WSL_DIAGNOSTICS_CONTEXT_KEY: AsyncMock(), **scope})
    monkeypatch.setattr(assembly, "EVERY_TOOL", [*assembly.EVERY_TOOL, WSL_DIAGNOSTICS_TOOL_NAME])
    _, captured = await assembly._assemble(monkeypatch, tmp_path, role=role, app=assembly._app_config())
    assert (WSL_DIAGNOSTICS_TOOL_NAME in {tool.name for tool in captured["tools"]}) is expected
    assert WSL_DIAGNOSTICS_TOOL_NAME not in MOMOBOT_MAX_TOOL_NAMES  # Ordinary client ceiling stays unchanged.


@pytest.mark.asyncio
async def test_role_authorization_still_narrows_admin_diagnostic_ceiling(monkeypatch, tmp_path):
    import test_momobot_max_assembly as assembly

    from deerflow.agents.lead_agent import agent

    original = agent._get_runtime_config
    monkeypatch.setattr(agent, "_get_runtime_config", lambda config: {**original(config), WSL_DIAGNOSTICS_CONTEXT_KEY: AsyncMock()})
    monkeypatch.setattr(assembly, "EVERY_TOOL", [*assembly.EVERY_TOOL, WSL_DIAGNOSTICS_TOOL_NAME])
    authorization = assembly.example_authorization()
    authorization["provider"]["config"]["roles"]["admin"]["tools"] = {"allow": "*", "deny": [WSL_DIAGNOSTICS_TOOL_NAME]}
    _, captured = await assembly._assemble(monkeypatch, tmp_path, role="admin", app=assembly._app_config(authorization=authorization))
    assert WSL_DIAGNOSTICS_TOOL_NAME not in {tool.name for tool in captured["tools"]}


def test_tool_registry_default_and_configured_alias_cannot_grant_capability(monkeypatch):
    from deerflow.config.tool_config import ToolConfig
    from deerflow.tools.tools import get_available_tools

    config = SimpleNamespace(tools=[], sandbox=SimpleNamespace(use="example.remote:Sandbox"), skill_evolution=SimpleNamespace(enabled=False), models=[], acp_agents={}, get_model_config=lambda _name: None)
    assert WSL_DIAGNOSTICS_TOOL_NAME not in {tool.name for tool in get_available_tools(include_mcp=False, app_config=config)}
    assert WSL_DIAGNOSTICS_TOOL_NAME in {tool.name for tool in get_available_tools(include_mcp=False, app_config=config, include_wsl_diagnostics=True)}
    config.tools = [ToolConfig(name="wsl_diagnostic", group="diagnostics", use="deerflow.tools.wsl_diagnostics:wsl_diagnostic")]
    monkeypatch.setattr("deerflow.tools.tools.resolve_variable", lambda *_: pytest.fail("host-disabled tool must not load"))
    assert WSL_DIAGNOSTICS_TOOL_NAME not in {tool.name for tool in get_available_tools(include_mcp=False, app_config=config)}


@pytest.mark.asyncio
async def test_authenticated_gateway_run_injects_fresh_callback_without_persisting_it(host, monkeypatch):
    from test_gateway_services import _make_start_run_persistence_context

    from app.gateway import services
    from app.gateway.run_models import RunCreateRequest
    from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config
    from deerflow.runtime.user_context import reset_current_user, set_current_user

    request, _, _ = _make_start_run_persistence_context()
    request.state.user = host.request.state.user
    request.state.auth = AuthContext(request.state.user, list(host.request.state.auth.permissions), "org", actor_user_id="actor", storage_user_id="actor")
    request.state.storage_user_id = "actor"
    request.state.actor_user_id = "actor"
    request.state.organization_id = "org"
    request.state.auth_source = "session"
    captured = []

    async def fake_run_agent(*args, **kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(services, "run_agent", fake_run_agent)
    monkeypatch.setattr(services, "resolve_agent_factory", lambda *_: object())
    monkeypatch.setattr(services, "_admit_effective_run_model", AsyncMock(return_value="offline"))
    monkeypatch.setattr(services, "apply_momobot_max_run_policy", AsyncMock())
    set_app_config(AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}, "momobot_max": {"enabled": True}}))
    token = set_current_user(request.state.user)
    try:
        body = RunCreateRequest(config={"context": {"agent_name": "momobot-max", WSL_DIAGNOSTICS_CONTEXT_KEY: "forged"}}, input={"messages": [{"role": "user", "content": "Check the PC kernel"}]})
        record = await services.start_run(body, "current", request)
        await record.task
        assert callable(captured[0]["ctx"].wsl_diagnostics)
        assert captured[0]["config"]["context"]["user_role"] == "admin"
        assert services.get_run_context(request).wsl_diagnostics is None
        assert "prepare_wsl_diagnostics" not in json.dumps(record.kwargs)
        result = json.loads(await wsl_diagnostic.coroutine("submit", runtime(captured[0]["ctx"].wsl_diagnostics, thread_id=record.thread_id, run_id=record.run_id), diagnostic="uname"))
        assert result["state"] == "pending"
        assert host.store.read(result["job_id"])["binding"][1:4] == ["org", "actor", "current"]
        record = await services.start_run(RunCreateRequest(input={"messages": [{"role": "user", "content": "Unrelated"}]}), "later", request)
        await record.task
        assert captured[1]["ctx"].wsl_diagnostics is None
    finally:
        reset_current_user(token)
        reset_app_config()


def test_worker_rejects_forged_callbacks_in_both_carriers_and_releases_host_reference():
    forged, host = object(), AsyncMock()
    config = {"context": {WSL_DIAGNOSTICS_CONTEXT_KEY: forged}, "configurable": {WSL_DIAGNOSTICS_CONTEXT_KEY: forged}}
    context = _build_runtime_context("thread", "run", config["context"])
    _install_runtime_context(config, context)
    assert WSL_DIAGNOSTICS_CONTEXT_KEY not in config["context"]
    assert WSL_DIAGNOSTICS_CONTEXT_KEY not in config["configurable"]
    assert RunContext(checkpointer=None).wsl_diagnostics is None
    context = _build_runtime_context("thread", "run", {}, wsl_diagnostics=host)
    _install_runtime_context(config, context)
    assert config["context"][WSL_DIAGNOSTICS_CONTEXT_KEY] is host
    _release_run_scoped_references([config], context, None)
    assert WSL_DIAGNOSTICS_CONTEXT_KEY not in context
    assert WSL_DIAGNOSTICS_CONTEXT_KEY not in config["context"]


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [PermissionError, FileNotFoundError])
async def test_optional_root_io_failure_preserves_admitted_gateway_run(host, monkeypatch, error_type):
    from test_gateway_services import _make_start_run_persistence_context

    from app.gateway import services
    from app.gateway.run_models import RunCreateRequest
    from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config
    from deerflow.runtime.user_context import reset_current_user, set_current_user

    request, run_store, _ = _make_start_run_persistence_context()
    request.state.user = host.request.state.user
    request.state.auth = AuthContext(request.state.user, list(host.request.state.auth.permissions), "org", actor_user_id="actor", storage_user_id="actor")
    request.state.storage_user_id = "actor"
    request.state.actor_user_id = "actor"
    request.state.organization_id = "org"
    request.state.auth_source = "session"
    worker = AsyncMock()
    monkeypatch.setattr(services, "run_agent", worker)
    monkeypatch.setattr(services, "resolve_agent_factory", lambda *_: object())
    monkeypatch.setattr(services, "_admit_effective_run_model", AsyncMock(return_value="offline"))
    monkeypatch.setattr(services, "apply_momobot_max_run_policy", AsyncMock())
    monkeypatch.setattr(BridgeStore, "from_environment", Mock(side_effect=error_type))
    set_app_config(AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}, "momobot_max": {"enabled": True}}))
    token = set_current_user(request.state.user)
    try:
        body = RunCreateRequest(config={"context": {"agent_name": "momobot-max"}}, input={"messages": [{"role": "user", "content": "An ordinary Momo conversation"}]})
        record = await services.start_run(body, "current", request)
        assert await run_store.get(record.run_id) is not None
        await record.task
        worker.assert_awaited_once()
        assert worker.call_args.kwargs["ctx"].wsl_diagnostics is None
        assert not host.store.path.exists()
    finally:
        reset_current_user(token)
        reset_app_config()
