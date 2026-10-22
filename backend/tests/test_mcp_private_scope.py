"""Synthetic private-MCP authorization checks; no providers or MCP processes."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.tools import StructuredTool, ToolException
from pydantic import ValidationError

from deerflow.config.extensions_config import ExtensionsConfig, McpServerConfig
from deerflow.mcp import cache, tools
from deerflow.mcp.private_scope import (
    bind_private_mcp_context,
    current_private_mcp_context,
    guard_private_mcp_tool,
    private_mcp_allowed,
    reset_private_mcp_context,
)
from deerflow.runtime.user_context import (
    AUTHENTICATED_CONTEXT_MARKER,
    AUTHENTICATED_CONTEXT_MARKER_KEY,
    WorkspaceStorageContext,
    reset_current_user,
    reset_storage_context,
    set_current_user,
    set_storage_context,
)

ACTOR = "synthetic-owner"
ORG = "synthetic-private-org"


def _server(**overrides):
    return McpServerConfig(type="http", url="https://synthetic.invalid/mcp", private_scope={"actor_user_id": ACTOR, "organization_id": ORG}, **overrides)


def _context(**overrides):
    return {
        AUTHENTICATED_CONTEXT_MARKER_KEY: AUTHENTICATED_CONTEXT_MARKER,
        "actor_user_id": ACTOR,
        "organization_id": ORG,
        "storage_user_id": ACTOR,
        **overrides,
    }


@contextmanager
def _identity(context=None, *, actor=ACTOR, role="admin"):
    context = _context() if context is None else context
    user = set_current_user(SimpleNamespace(id=actor, system_role=role))
    storage = set_storage_context(WorkspaceStorageContext(actor, context.get("organization_id"), context.get("storage_user_id", actor)))
    binding = bind_private_mcp_context(context)
    try:
        yield
    finally:
        reset_private_mcp_context(binding)
        reset_storage_context(storage)
        reset_current_user(user)


def _tool(name="private_query", calls=None):
    async def query(runtime=None, **arguments):
        if calls is not None:
            calls.append(arguments)
        return "synthetic-result"

    return StructuredTool(name=name, description="Synthetic query", args_schema={"type": "object", "properties": {}}, coroutine=query)


def test_policy_requires_exact_private_actor_organization_and_storage():
    server = _server()
    with _identity():
        assert private_mcp_allowed(server)
    for context, actor in [
        (_context(actor_user_id="synthetic-other", storage_user_id="synthetic-other"), "synthetic-other"),
        (_context(organization_id="synthetic-client-org"), ACTOR),
        (_context(storage_user_id="synthetic-shared-storage"), ACTOR),
        (_context(organization_id=None), ACTOR),
    ]:
        with _identity(context, actor=actor):
            assert not private_mcp_allowed(server)


@pytest.mark.parametrize(
    "context",
    [
        {},
        _context(**{AUTHENTICATED_CONTEXT_MARKER_KEY: True}),
        _context(**{AUTHENTICATED_CONTEXT_MARKER_KEY: "forwarded-marker"}),
        _context(channel_name="slack"),
        _context(channel_name="github"),
        _context(channel_name=None),
        _context(public_news_channel=False),
        _context(public_news_channel=True),
        _context(non_interactive=True),
    ],
)
def test_unknown_forged_background_and_channel_contexts_deny(context):
    with _identity(context):
        assert not private_mcp_allowed(_server())


def test_forwarded_auth_marker_cannot_change_authenticated_actor_or_internal_origin():
    with _identity(_context(), actor="synthetic-other"):
        assert not private_mcp_allowed(_server())
    with _identity(_context(), role="internal"):
        assert not private_mcp_allowed(_server())


def test_inherited_binding_checks_live_principal_and_workspace():
    with _identity():
        token = set_current_user(SimpleNamespace(id="synthetic-other"))
        try:
            assert not private_mcp_allowed(_server())
        finally:
            reset_current_user(token)
        token = set_storage_context(WorkspaceStorageContext(ACTOR, "synthetic-client-org", ACTOR))
        try:
            assert not private_mcp_allowed(_server())
        finally:
            reset_storage_context(token)
    assert current_private_mcp_context() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["http", "sse", "stdio"])
async def test_captured_tool_cannot_cross_principals_or_trust_runtime_fields(transport):
    calls = []
    server = _server()
    server.type = transport
    with _identity():
        guarded = guard_private_mcp_tool(_tool(calls=calls), server)
        assert await guarded.coroutine() == "synthetic-result"
    with _identity(actor="synthetic-other"):
        forged_runtime = SimpleNamespace(context=_context(user_id=ACTOR, private_scope=True, user_role="owner"))
        with pytest.raises(ToolException, match="operator-bound private web"):
            await guarded.coroutine(runtime=forged_runtime)
    with _identity(_context(channel_name="slack")):
        with pytest.raises(ToolException):
            await guarded.coroutine()
    assert calls == [{}]


@pytest.mark.parametrize("policy", [{}, {"actor_user_id": "", "organization_id": ORG}, {"actor_user_id": ACTOR, "organization_id": ORG, "enabled": False}])
def test_malformed_private_policy_cannot_silently_become_public(policy):
    with pytest.raises(ValidationError):
        McpServerConfig(private_scope=policy)


def test_private_server_rejects_background_task_toolsets():
    with pytest.raises(ValidationError, match="private_scope"):
        _server(task_toolsets=[{"name": "synthetic-job", "submit_tool": "start", "status_tool": "status", "cancel_tool": "cancel"}])


@pytest.mark.asyncio
async def test_discovery_filters_before_client_connections_and_keeps_public_catalog_separate(monkeypatch):
    from langchain_mcp_adapters import client

    config = ExtensionsConfig(mcp_servers={"public": McpServerConfig(type="http", url="https://public.synthetic.invalid/mcp"), "private": _server()})
    clients = []

    class FakeClient:
        def __init__(self, connections, **kwargs):
            self.connections = connections
            self.callbacks = None
            self.tool_interceptors = []
            clients.append(tuple(connections))

        async def get_tools(self, *, server_name):
            return [_tool(server_name + "_query")]

    monkeypatch.setattr(client, "MultiServerMCPClient", FakeClient)
    monkeypatch.setattr(ExtensionsConfig, "from_file", lambda: config)
    monkeypatch.setattr(tools, "validate_mcp_task_config_snapshot", lambda _config: None)
    monkeypatch.setattr(tools, "get_initial_oauth_headers", AsyncMock(return_value={}))
    with _identity({}):
        assert await tools.get_mcp_tools(private_only=True) == []
        assert clients == []
        assert [tool.name for tool in await tools.get_mcp_tools()] == ["public_query"]
    with _identity():
        assert [tool.name for tool in await tools.get_mcp_tools()] == ["public_query"]
        private = await tools.get_mcp_tools(private_only=True)
        assert [tool.name for tool in private] == ["private_query"]
    assert clients == [("public",), ("public",), ("private",)]
    with _identity(actor="synthetic-other"):
        with pytest.raises(ToolException):
            await private[0].coroutine()


def test_global_cache_never_publishes_private_tools_and_discovery_preserves_context(monkeypatch):
    public = _tool("public_query")
    seen = []

    async def load(*, private_only=False):
        assert private_only
        assert current_private_mcp_context() is not None
        seen.append("private-discovery")
        return [guard_private_mcp_tool(_tool(), _server())]

    monkeypatch.setattr(cache, "_cache_initialized", True)
    monkeypatch.setattr(cache, "_mcp_tools_cache", [public])
    monkeypatch.setattr(cache, "_is_cache_stale", lambda: False)
    monkeypatch.setattr(tools, "get_mcp_tools", load)
    with _identity():
        assert [tool.name for tool in cache.get_cached_mcp_tools()] == ["public_query", "private_query"]
    with _identity(actor="synthetic-other"):
        # No restricted discovery is attempted without an accepted private binding.
        assert cache.get_cached_mcp_tools() == [public]
    assert cache._mcp_tools_cache == [public]
    assert seen == ["private-discovery"]


@pytest.mark.asyncio
async def test_raw_background_caller_denies_restricted_server_before_connection(monkeypatch):
    from deerflow.mcp import task_tool_caller

    config = ExtensionsConfig(mcp_servers={"private": _server()})
    caller = task_tool_caller.McpTaskToolCaller(config)
    monkeypatch.setattr(task_tool_caller, "build_server_params", lambda *_: pytest.fail("restricted background connection attempted"))
    with _identity():
        with pytest.raises(ToolException, match="background"):
            await caller.call_tool(server_name="private", tool_name="query", arguments={}, user_id=ACTOR, thread_id="synthetic-thread")


def test_builtin_momobot_max_keeps_existing_mcp_and_tool_ceiling(monkeypatch):
    from deerflow.config import builtin_agents

    monkeypatch.setattr(builtin_agents, "_momobot_max_model", lambda: "synthetic-model")
    config = builtin_agents.get_builtin_agent_config("momobot-max")
    assert config.mcp_plugins == []
    assert set(config.tool_names) == {"web_search", "web_fetch", "read_file", "write_file", "present_files", "ask_clarification", "view_image", "task", "tool_search"}


@pytest.mark.asyncio
async def test_private_discovery_from_sync_cache_in_running_loop_preserves_trusted_binding(monkeypatch):
    async def load(*, private_only=False):
        assert private_only and current_private_mcp_context() is not None
        return [_tool()]

    monkeypatch.setattr(cache, "_cache_initialized", True)
    monkeypatch.setattr(cache, "_mcp_tools_cache", [])
    monkeypatch.setattr(cache, "_is_cache_stale", lambda: False)
    monkeypatch.setattr(tools, "get_mcp_tools", load)
    with _identity():
        assert [tool.name for tool in cache.get_cached_mcp_tools()] == ["private_query"]
    assert cache._mcp_tools_cache == []


@pytest.mark.asyncio
async def test_real_adapter_and_toolnode_preserve_runtime_and_deny_before_new_session(monkeypatch):
    from langchain_core.messages import AIMessage
    from langchain_mcp_adapters import tools as adapter
    from langgraph.graph import END, START, MessagesState, StateGraph
    from langgraph.prebuilt import ToolNode
    from mcp.types import CallToolResult, TextContent, Tool

    entered = []
    runtimes = []

    @asynccontextmanager
    async def session(*_args, **_kwargs):
        entered.append("session")
        yield SimpleNamespace(initialize=AsyncMock(), call_tool=AsyncMock(return_value=CallToolResult(content=[TextContent(type="text", text="synthetic-result")])))

    async def interceptor(request, handler):
        runtimes.append(request.runtime)
        return await handler(request)

    monkeypatch.setattr(adapter, "create_session", session)
    raw = adapter.convert_mcp_tool_to_langchain_tool(
        None, Tool(name="query", description="Synthetic", inputSchema={"type": "object", "properties": {}}), connection={"transport": "http", "url": "https://synthetic.invalid/mcp"}, tool_interceptors=[interceptor]
    )
    with _identity():
        guarded = guard_private_mcp_tool(raw, _server())
        builder = StateGraph(MessagesState)
        builder.add_node("tools", ToolNode([guarded], handle_tool_errors=False))
        builder.add_edge(START, "tools")
        builder.add_edge("tools", END)
        graph = builder.compile()
        state = {"messages": [AIMessage(content="", tool_calls=[{"name": "query", "args": {}, "id": "synthetic-call"}])]}
        result = await graph.ainvoke(state, context={"synthetic": "runtime"})
        assert result["messages"][-1].content[0]["text"] == "synthetic-result"
        assert runtimes[0].context == {"synthetic": "runtime"}
    with _identity(actor="synthetic-other"):
        with pytest.raises(ToolException):
            await graph.ainvoke(state, context=_context())
    assert entered == ["session"]


@pytest.mark.asyncio
@pytest.mark.parametrize("origin", ["private", "forged", "channel", "background", "factory-error"])
async def test_worker_binds_through_assembly_and_graph_then_resets(origin):
    from deerflow.runtime.runs.manager import RunRecord, RunStartOutcome
    from deerflow.runtime.runs.schemas import DisconnectMode, RunStatus
    from deerflow.runtime.runs.worker import RunContext, run_agent

    observed = []

    class Agent:
        metadata = {}
        checkpointer = None
        store = None
        interrupt_before_nodes = []
        interrupt_after_nodes = []

        async def astream(self, *_args, **_kwargs):
            observed.append(("graph", current_private_mcp_context() is not None))
            return
            yield

    def factory(**_kwargs):
        observed.append(("assembly", current_private_mcp_context() is not None))
        if origin == "factory-error":
            raise RuntimeError("synthetic assembly failure")
        return Agent()

    manager = SimpleNamespace(**{name: AsyncMock() for name in ["wait_for_prior_finalizing", "set_status", "set_status_if_not_cancelled", "update_model_name", "update_run_completion", "cleanup"]})
    manager.try_start = AsyncMock(return_value=RunStartOutcome.started)
    manager.has_later_run = AsyncMock(return_value=False)
    manager.has_later_started_run = AsyncMock(return_value=False)
    manager.set_status_if_not_cancelled = AsyncMock(return_value=None)
    bridge = SimpleNamespace(publish=AsyncMock(), publish_end=AsyncMock(), cleanup=AsyncMock())
    record = RunRecord(run_id="synthetic-run", thread_id="synthetic-thread", assistant_id="lead-agent", status=RunStatus.pending, on_disconnect=DisconnectMode.cancel)
    record.abort_event = asyncio.Event()
    context = _context()
    if origin == "forged":
        context[AUTHENTICATED_CONTEXT_MARKER_KEY] = True
    elif origin == "channel":
        context["channel_name"] = "slack"
    elif origin == "background":
        context["non_interactive"] = True
    # Auth identity exists, but no private binding is inherited by the worker.
    with _identity(_context(**{AUTHENTICATED_CONTEXT_MARKER_KEY: False})):
        assert current_private_mcp_context() is None
        await run_agent(bridge, manager, record, ctx=RunContext(checkpointer=None), agent_factory=factory, graph_input={"messages": []}, config={"context": context})
        assert current_private_mcp_context() is None
    allowed = origin in {"private", "factory-error"}
    assert observed == [("assembly", allowed)] + ([] if origin == "factory-error" else [("graph", allowed)])
