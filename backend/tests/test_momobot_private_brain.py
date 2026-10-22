"""Run-local Max Brain assembly against synthetic snapshot and MCP transport."""

from __future__ import annotations

import asyncio
import json
import threading
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import ToolException
from mcp.types import CallToolResult, TextContent, Tool

from deerflow.capabilities.runtime import installation_id
from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config
from deerflow.config.builtin_agents import MOMOBOT_MAX_TOOL_NAMES, get_builtin_agent_config
from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.mcp.private_scope import PRIVATE_MCP_SESSION_CONTEXT_KEY, PRIVATE_MCP_SESSION_MARKER, bind_private_mcp_context, reset_private_mcp_context
from deerflow.runtime.user_context import (
    AUTHENTICATED_CONTEXT_MARKER,
    AUTHENTICATED_CONTEXT_MARKER_KEY,
    WorkspaceStorageContext,
    get_current_user,
    reset_current_user,
    reset_storage_context,
    set_current_user,
    set_storage_context,
)

ACTOR = "synthetic-owner"
ORG = "synthetic-private-org"
READS = ("brain_now", "brain_client", "brain_open_items", "brain_systems")
SNAPSHOT = {name: {"synthetic": name} for name in READS}


class SyntheticModel(BaseChatModel):
    @property
    def _llm_type(self):
        return "synthetic-no-provider"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, **kwargs):
        pytest.fail("This assembly test must not invoke a model")


@contextmanager
def _scope(*, actor=ACTOR, organization=ORG, storage=None, origin="session"):
    storage = storage or actor
    context = {
        AUTHENTICATED_CONTEXT_MARKER_KEY: AUTHENTICATED_CONTEXT_MARKER,
        PRIVATE_MCP_SESSION_CONTEXT_KEY: PRIVATE_MCP_SESSION_MARKER,
        "is_internal": False,
        "actor_user_id": actor,
        "organization_id": organization,
        "storage_user_id": storage,
    }
    if origin == "internal":
        context["is_internal"] = True
    elif origin in {"pat", "auth_disabled", "unknown"}:
        context.pop(PRIVATE_MCP_SESSION_CONTEXT_KEY)
    elif origin == "channel":
        context["channel_name"] = "slack"
    elif origin == "background":
        context["non_interactive"] = True
    user = set_current_user(SimpleNamespace(id=actor, system_role="admin"))
    workspace = set_storage_context(WorkspaceStorageContext(actor, organization, storage))
    binding = bind_private_mcp_context(context)
    try:
        yield
    finally:
        reset_private_mcp_context(binding)
        reset_storage_context(workspace)
        reset_current_user(user)


@pytest.fixture
def harness(monkeypatch, tmp_path):
    from langchain_mcp_adapters import client
    from langchain_mcp_adapters import tools as adapter

    import deerflow.tools
    from deerflow.agents.lead_agent import agent, prompt
    from deerflow.mcp import cache

    example = yaml.safe_load((Path(__file__).parents[2] / "config.example.yaml").read_text(encoding="utf-8"))
    app = AppConfig.model_validate(
        {
            **example,
            "models": [{"name": "synthetic-model", "use": "langchain_openai:ChatOpenAI", "model": "synthetic-model"}],
            "tools": [],
            "momobot_max": {"enabled": True, "model": "synthetic-model"},
            "authorization": {"enabled": True, "default_role": "admin", "provider": {"use": "deerflow.authz.rbac:RbacAuthorizationProvider", "config": {"roles": {"admin": {"tools": {"allow": "*"}, "models": {"allow": "*"}}}}}},
            "tool_search": {"enabled": False},
        }
    )
    app.summarization.enabled = False
    app.memory.enabled = False
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path / "home"))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    set_app_config(app)
    monkeypatch.setattr(agent, "create_chat_model", lambda **_kw: SyntheticModel())
    for name in ("_build_user_profile_section", "_build_acp_section", "_build_custom_mounts_section"):
        monkeypatch.setattr(prompt, name, lambda *_a, **_kw: "")
    path = tmp_path / "extensions_config.json"
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(path))
    raw = {"mcpServers": {"brain": {"type": "http", "url": "https://brain.synthetic.invalid/mcp", "private_scope": {"actor_user_id": ACTOR, "organization_id": ORG}, "capability": {"id": "synthetic-brain-installation"}}}}

    def save():
        path.write_text(json.dumps(raw), encoding="utf-8")

    save()
    # Keep the existing global cache public-only; private discovery remains real.
    monkeypatch.setattr(cache, "_cache_initialized", True)
    monkeypatch.setattr(cache, "_mcp_tools_cache", [])
    monkeypatch.setattr(cache, "_is_cache_stale", lambda: False)
    discovered = []
    client_connections = []
    transport_calls = []
    transport_entries = []

    @asynccontextmanager
    async def session(connection, **_kw):
        async def call_tool(name, arguments, **kwargs):
            transport_calls.append(name)
            transport_entries.append((connection["url"], name))
            return CallToolResult(content=[TextContent(type="text", text=json.dumps(SNAPSHOT[name]))])

        async def initialize():
            return None

        yield SimpleNamespace(initialize=initialize, call_tool=call_tool)

    monkeypatch.setattr(adapter, "create_session", session)

    def server_tools(server_name, connection, prefix):
        discovered.append(server_name)
        names = (*READS, "brain_search", "brain_capture", "brain_refresh", "web_search") if server_name == "brain" else ("brain_now", "public_query")
        return [
            adapter.convert_mcp_tool_to_langchain_tool(None, Tool(name=name, description="Synthetic read", inputSchema={"type": "object", "properties": {}}), connection=connection, server_name=server_name, tool_name_prefix=prefix)
            for name in names
        ]

    class FakeClient:
        def __init__(self, connections, **kwargs):
            client_connections.append(tuple(sorted(connections)))
            self.connections = connections
            self.callbacks = None
            self.tool_interceptors = []

        async def get_tools(self, *, server_name):
            return server_tools(server_name, self.connections[server_name], True)

    async def load_tools(_session, *, connection, server_name, tool_name_prefix, **kwargs):
        return server_tools(server_name, connection, tool_name_prefix)

    monkeypatch.setattr(client, "MultiServerMCPClient", FakeClient)
    monkeypatch.setattr(adapter, "load_mcp_tools", load_tools)
    selected = []
    barrier = [None]
    real_available = deerflow.tools.get_available_tools

    def available(**kwargs):
        selected.append((str(get_current_user().id), kwargs["mcp_plugins"]))
        if barrier[0] is not None:
            barrier[0].wait(timeout=10)
        return real_available(**kwargs)

    monkeypatch.setattr(deerflow.tools, "get_available_tools", available)
    captures = {}
    real_create = agent.create_agent

    def create(**kwargs):
        captures[str(get_current_user().id)] = kwargs
        return real_create(**kwargs)

    monkeypatch.setattr(agent, "create_agent", create)

    def assemble():
        config = {"configurable": {"thread_id": "synthetic-thread"}, "context": {"agent_name": "momobot-max", "user_id": str(get_current_user().id), "user_role": "admin"}}
        agent._assemble_lead_agent(config, app_config=app)
        return captures[str(get_current_user().id)], config

    try:
        yield SimpleNamespace(
            app=app, path=path, raw=raw, save=save, assemble=assemble, selected=selected, discovered=discovered, client_connections=client_connections, transport_calls=transport_calls, transport_entries=transport_entries, barrier=barrier
        )
    finally:
        reset_app_config()


@pytest.mark.asyncio
@pytest.mark.parametrize("prefix", [True, False])
async def test_private_max_reaches_real_selection_authorization_and_four_adapter_reads(harness, prefix):
    harness.raw["mcpServers"]["brain"]["tool_name_prefix"] = prefix
    harness.save()
    baseline = get_builtin_agent_config("momobot-max").model_dump()
    names = {f"brain_{name}" if prefix else name for name in READS}
    with _scope():
        captured, config = harness.assemble()
        actual = {tool.name: tool for tool in captured["tools"]}
        assert names <= actual.keys()
        from deerflow.tools.mcp_metadata import is_mcp_tool

        assert {name for name, tool in actual.items() if is_mcp_tool(tool)} == names
        from deerflow.agents.middlewares.skill_tool_policy_middleware import SkillToolPolicyMiddleware

        policy = next(m for m in captured["middleware"] if isinstance(m, SkillToolPolicyMiddleware))
        assert names <= set(policy.release_policy_parameters()["owner_tool_names"])
        assert actual.keys() <= set(MOMOBOT_MAX_TOOL_NAMES) | names
        assert harness.selected == [(ACTOR, ["synthetic-brain-installation"])]
        assert config["metadata"]["mcp_plugins"] == []  # no delegation/global policy change
        for name in sorted(names):
            content, _artifact = await actual[name].coroutine()
            raw_name = name[len("brain_") :] if prefix else name
            assert json.loads(content[0]["text"]) == SNAPSHOT[raw_name]
        assert get_builtin_agent_config("momobot-max").model_dump() == baseline
    assert set(harness.transport_calls) == set(READS)
    with _scope(actor="synthetic-other"):
        with pytest.raises(ToolException):
            await actual[next(iter(names))].coroutine()
    assert len(harness.transport_calls) == 4


@pytest.mark.parametrize("origin", ["internal", "pat", "auth_disabled", "unknown", "channel", "background"])
def test_other_origins_keep_global_max_ceiling_and_skip_mcp_discovery(harness, origin):
    with _scope(origin=origin):
        captured, _config = harness.assemble()
    assert {tool.name for tool in captured["tools"]} <= set(MOMOBOT_MAX_TOOL_NAMES)
    assert harness.selected == [(ACTOR, [])]
    assert harness.discovered == []


@pytest.mark.parametrize("scope", [{"actor": "synthetic-other"}, {"organization": "synthetic-other-org"}, {"storage": "synthetic-shared-storage"}])
def test_wrong_actor_organization_or_shared_storage_does_not_add_brain(harness, scope):
    with _scope(**scope):
        captured, _config = harness.assemble()
    assert {tool.name for tool in captured["tools"]} <= set(MOMOBOT_MAX_TOOL_NAMES)
    assert harness.selected[-1][1] == []
    assert harness.discovered == []


@pytest.mark.parametrize("state", ["disabled", "unrestricted", "other-name", "ambiguous-id"])
def test_only_exact_enabled_private_brain_installation_is_selected(harness, state):
    server = harness.raw["mcpServers"]["brain"]
    if state == "disabled":
        server["enabled"] = False
    elif state == "unrestricted":
        server.pop("private_scope")
    elif state == "other-name":
        harness.raw["mcpServers"]["other-brain"] = harness.raw["mcpServers"].pop("brain")
    else:
        harness.raw["mcpServers"]["other-brain"] = {**server, "enabled": False}
    harness.save()
    with _scope():
        captured, _config = harness.assemble()
    assert {tool.name for tool in captured["tools"]} <= set(MOMOBOT_MAX_TOOL_NAMES)
    assert harness.discovered == []


def test_existing_authorization_can_deny_an_individually_selected_brain_read(harness):
    harness.app.authorization.provider.config["roles"]["admin"]["tools"]["deny"] = ["brain_brain_client"]
    with _scope():
        captured, _config = harness.assemble()
    actual = {tool.name for tool in captured["tools"]}
    assert {"brain_brain_now", "brain_brain_open_items", "brain_brain_systems"} <= actual
    assert "brain_brain_client" not in actual


@pytest.mark.asyncio
async def test_two_concurrent_contexts_have_independent_run_local_max_tools(harness):
    baseline = get_builtin_agent_config("momobot-max").model_dump()
    harness.barrier[0] = threading.Barrier(2)

    def run(actor):
        with _scope(actor=actor):
            captured, _config = harness.assemble()
            return {tool.name for tool in captured["tools"]}

    private, other = await asyncio.gather(asyncio.to_thread(run, ACTOR), asyncio.to_thread(run, "synthetic-other"))
    assert {f"brain_{name}" for name in READS} <= private
    assert other <= set(MOMOBOT_MAX_TOOL_NAMES)
    assert get_builtin_agent_config("momobot-max").model_dump() == baseline


def test_deterministic_installation_id_is_used_when_no_explicit_id_exists(harness):
    harness.raw["mcpServers"]["brain"].pop("capability")
    harness.save()
    server = ExtensionsConfig.from_file().mcp_servers["brain"]
    with _scope():
        captured, _config = harness.assemble()
    assert harness.selected == [(ACTOR, [installation_id("brain", server.model_dump())])]
    assert {f"brain_{name}" for name in READS} <= {tool.name for tool in captured["tools"]}


def test_public_mcp_catalog_cannot_join_private_max_selection(harness, monkeypatch):
    from langchain_core.tools import StructuredTool

    from deerflow.mcp import cache
    from deerflow.mcp.private_scope import matches_private_mcp_discovery
    from deerflow.tools.mcp_metadata import tag_mcp_tool

    async def public_query(runtime=None):
        pytest.fail("Public MCP must not be callable through private Max selection")

    public = StructuredTool(name="public_query", description="Synthetic public", args_schema={"type": "object", "properties": {}}, coroutine=public_query)
    tag_mcp_tool(public, server_name="public", transport="http")
    harness.raw["mcpServers"]["public"] = {"type": "http", "url": "https://public.synthetic.invalid/mcp"}
    harness.save()
    monkeypatch.setattr(cache, "_mcp_tools_cache", [public])
    selected_server = ExtensionsConfig.from_file().mcp_servers["brain"]
    public.metadata = {
        **(public.metadata or {}),
        "_deerflow_private_mcp_provenance": {"server_name": "brain", "configuration": selected_server.model_dump(mode="json")},
    }
    assert not matches_private_mcp_discovery(public, selected_server, server_name="brain")
    with _scope():
        captured, _config = harness.assemble()
    assert "public_query" not in {tool.name for tool in captured["tools"]}
    assert harness.discovered == ["brain"]


@pytest.mark.asyncio
async def test_cold_private_max_starts_only_selected_brain_during_public_transport_aba(harness, monkeypatch):
    import deerflow.tools
    from deerflow.mcp import cache
    from deerflow.mcp.private_scope import matches_private_mcp_discovery

    harness.raw["mcpServers"]["unrelated-public"] = {"type": "http", "url": "https://public.synthetic.invalid/mcp"}
    harness.raw["mcpServers"]["unrelated-private"] = {
        "type": "http",
        "url": "https://private.synthetic.invalid/mcp",
        "private_scope": {"actor_user_id": ACTOR, "organization_id": ORG},
        "capability": {"id": "synthetic-unrelated-private-installation"},
    }
    harness.save()
    original = json.loads(json.dumps(harness.raw))
    selected_server = ExtensionsConfig.from_file().mcp_servers["brain"]
    # A cold global cache must stay untouched while a temporary public B exists.
    monkeypatch.setattr(cache, "_cache_initialized", False)
    monkeypatch.setattr(cache, "_mcp_tools_cache", None)
    available = deerflow.tools.get_available_tools

    def public_transport_then_restore(**kwargs):
        public = harness.raw["mcpServers"]["brain"]
        public.pop("private_scope")
        public["url"] = "https://old-public.synthetic.invalid/mcp"
        harness.save()
        try:
            return available(**kwargs)
        finally:
            harness.raw.clear()
            harness.raw.update(original)
            harness.save()

    monkeypatch.setattr(deerflow.tools, "get_available_tools", public_transport_then_restore)
    with _scope():
        captured, _config = harness.assemble()
        assert ExtensionsConfig.from_file().mcp_servers["brain"].model_dump() == selected_server.model_dump()
        actual = {tool.name: tool for tool in captured["tools"]}
        expected = {f"brain_{name}" for name in READS}
        assert expected <= actual.keys()
        assert actual.keys() <= set(MOMOBOT_MAX_TOOL_NAMES) | expected
        assert len(MOMOBOT_MAX_TOOL_NAMES) == 9
        assert cache._cache_initialized is False
        assert cache._mcp_tools_cache is None
        for name in expected:
            assert matches_private_mcp_discovery(actual[name], selected_server, server_name="brain")
    assert harness.client_connections == [("brain",)]
    assert harness.discovered == ["brain"]
    assert harness.transport_entries == []


def test_selection_requires_existing_max_name_and_readable_config(harness):
    from deerflow.agents.lead_agent.private_brain import private_brain_for_max

    with _scope():
        assert private_brain_for_max("synthetic-other-agent") is None
        harness.raw["mcpServers"] = {}
        harness.save()
        assert private_brain_for_max("momobot-max") is None
        harness.path.write_text("{", encoding="utf-8")
        assert private_brain_for_max("momobot-max") is None
