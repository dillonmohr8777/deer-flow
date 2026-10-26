"""What a MomoBot Max run is actually assembled from: model, effort, tools, delegation and instructions."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import yaml
from _role_tier_example import example_authorization
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool

from app.gateway.momobot_max import apply_run_policy
from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config
from deerflow.config.builtin_agents import MOMOBOT_MAX_TOOL_NAMES

EVERY_TOOL = [
    "web_search",
    "web_fetch",
    "read_file",
    "write_file",
    "present_files",
    "ask_clarification",
    "view_image",
    "task",
    "bash",
    "ls",
    "str_replace",
    "update_agent",
    "propose_action",
    "list_uploaded_files",
    "memory_search",
    "client_mcp_tool",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["staff", "staff_user", "staff_exec", "client", "forged", "wrong_project", "wrong_client", "channel", "subagent", "missing"])
async def test_only_host_bound_staff_client_project_adds_shelf_reads(monkeypatch, tmp_path, case):
    from deerflow.projects.access import ClientProjectReadAccess
    from deerflow.runtime.context_keys import CLIENT_PROJECT_ACCESS_CONTEXT_KEY, PROJECT_CONTEXT_KEY

    snapshot = {"project_id": "project-a", "client_id": "client-a", "name": "A", "instructions": ""}
    access = ClientProjectReadAccess(project_id="project-a", client_id="client-a", authorize=AsyncMock())
    context = {PROJECT_CONTEXT_KEY: snapshot, CLIENT_PROJECT_ACCESS_CONTEXT_KEY: access}
    if case == "forged":
        context[CLIENT_PROJECT_ACCESS_CONTEXT_KEY] = {"project_id": "project-a", "client_id": "client-a"}
    elif case == "wrong_project":
        snapshot["project_id"] = "project-b"
    elif case == "wrong_client":
        snapshot["client_id"] = "client-b"
    elif case == "channel":
        context["channel_name"] = "slack"
    elif case == "subagent":
        context["is_subagent"] = True
    elif case == "missing":
        context.pop(CLIENT_PROJECT_ACCESS_CONTEXT_KEY)
    role = {"client": "client", "staff_user": "user", "staff_exec": "exec"}.get(case, "admin")
    _, captured = await _assemble(monkeypatch, tmp_path, role=role, app=_app_config(), keys=("c-max",), context=context)
    shelf = {"list_project_documents", "read_project_document", "verify_quote"}
    names = {tool.name for tool in captured["tools"]}
    assert names & shelf == (shelf if case in {"staff", "staff_user", "staff_exec"} else set())
    assert {"bash", "update_agent", "client_mcp_tool"}.isdisjoint(names)
    assert ("propose_action" in names) is (role in {"user", "exec", "admin"} and case not in {"channel", "subagent"})


class OfflineModel(BaseChatModel):
    @property
    def _llm_type(self):
        return "offline-momobot-max"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="offline"))])


def _app_config(**extra) -> AppConfig:
    example = AppConfig.model_validate(yaml.safe_load((Path(__file__).parents[2] / "config.example.yaml").read_text()))
    model = {"name": "claude-opus-5-5", "use": "langchain_openai:ChatOpenAI", "model": "claude-opus-5-5", "supports_thinking": True, "supports_reasoning_effort": True}
    base = {"name": "claude-haiku-5-5", "use": "langchain_openai:ChatOpenAI", "model": "claude-haiku-5-5", "supports_thinking": True, "supports_reasoning_effort": True}
    max_settings = {"enabled": True, "default_effort": "high", "client_effort": {"acme-dental": "medium"}, "clients": ["acme-dental", "c-max"]}
    app = AppConfig.model_validate({**example.model_dump(), "models": [model, base], "momobot_max": max_settings, **extra})
    app.summarization.enabled = False
    return app


async def _assemble(monkeypatch, tmp_path, *, role: str, app: AppConfig, keys=(), context=None, real_tools=False):
    import deerflow.tools
    from deerflow.agents.lead_agent import agent, prompt

    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    set_app_config(app)  # the built-in agent reads the process-wide config, like production

    async def client_keys(_user_id, _organization_id=None):
        return keys

    monkeypatch.setattr("app.gateway.momobot_max.client_keys_for_user", client_keys)
    # The dedicated-workspace gate has its own suite; assembly runs behind it.
    monkeypatch.setattr("app.gateway.client_workspace.require_client_workspace", AsyncMock())
    created = {}

    def create_chat_model(**kwargs):
        created.update(kwargs)
        return OfflineModel()

    monkeypatch.setattr(agent, "create_chat_model", create_chat_model)
    for name in ("_build_user_profile_section", "_build_acp_section", "_build_custom_mounts_section"):
        monkeypatch.setattr(prompt, name, lambda *a, **kw: "")

    def fixture_tool(name):
        @tool(name)
        def fake(query: str = "") -> str:
            """Synthetic tool."""
            return "ok"

        return fake

    if not real_tools:
        monkeypatch.setattr(deerflow.tools, "get_available_tools", lambda **kw: [fixture_tool(n) for n in EVERY_TOOL])
    captured = {}
    real_create = agent.create_agent

    def capture(**kwargs):
        captured.update(kwargs)
        return real_create(**kwargs)

    monkeypatch.setattr(agent, "create_agent", capture)

    # The run config exactly as start_run leaves it: the policy has run, then identity is stamped.
    config = {"configurable": {"thread_id": "t-1"}, "context": {"agent_name": "momobot-max", "user_id": "u-1", "user_role": role, "model_name": "claude-opus-5-5"}}
    await apply_run_policy(config, user=SimpleNamespace(id="u-1", system_role=role, oauth_provider=None, oauth_id=None), actor_user_id="u-1", app_config=app)
    config["context"]["user_role"] = role
    config["context"].update(context or {})
    try:
        agent._assemble_lead_agent(config, app_config=app)
    finally:
        reset_app_config()
    return created, captured


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["user", "exec", "admin", "client"])
@pytest.mark.parametrize("allowed", [True, False])
async def test_shared_workspace_max_can_propose_only_for_authorized_staff(monkeypatch, tmp_path, role, allowed):
    from app.gateway.auth_disabled import AUTH_SOURCE_SESSION
    from app.gateway.services import inject_authenticated_user_context
    from deerflow.tools.builtins import propose_action

    authorization = example_authorization()
    roles = authorization["provider"]["config"]["roles"]
    for staff in ("user", "exec"):
        roles[staff]["models"]["allow"].append("claude-haiku-5-5-max")
    roles[role]["tools"] = {"allow": ["present_files", "propose_action"] if allowed else ["present_files"]}
    app = _app_config(authorization=authorization, tools=[])
    app = AppConfig.model_validate({**app.model_dump(), "models": [*app.models, app.models[1].model_copy(update={"name": "claude-haiku-5-5-max", "model": "claude-haiku-5-5-max"})]})
    app.momobot_max.staff_model = "claude-haiku-5-5-max"
    user = SimpleNamespace(id="u-1", system_role=role, oauth_provider=None, oauth_id=None)
    identity = {}
    inject_authenticated_user_context(
        identity,
        SimpleNamespace(state=SimpleNamespace(user=user, auth_source=AUTH_SOURCE_SESSION, actor_user_id=user.id, storage_user_id="storage-agency", organization_id="org-agency", organization_role="member")),
    )

    created, captured = await _assemble(monkeypatch, tmp_path, role=role, app=app, keys=("c-max",), context=identity["context"], real_tools=True)

    if role in {"user", "exec"}:
        assert created["name"] == "claude-haiku-5-5-max"
    assert (propose_action in captured["tools"]) is (allowed and role != "client")
    assert "present_files" in {tool.name for tool in captured["tools"]}


@pytest.mark.asyncio
@pytest.mark.parametrize("context", [{"user_role": None}, {"channel_name": "slack"}, {"is_subagent": True}])
async def test_max_staff_proposal_tool_requires_a_staff_lead_run(monkeypatch, tmp_path, context):
    _, captured = await _assemble(monkeypatch, tmp_path, role="admin", app=_app_config(), context=context)

    assert "propose_action" not in {tool.name for tool in captured["tools"]}


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["client", "exec", "admin"])
async def test_a_momobot_max_run_has_the_models_effort_delegation_and_soul(monkeypatch, tmp_path, role):
    created, captured = await _assemble(monkeypatch, tmp_path, role=role, app=_app_config(authorization=example_authorization()), keys=("c-max",))

    assert (created["name"], created["thinking_enabled"], created["reasoning_effort"]) == ("claude-opus-5-5", True, "high")
    assert "<momobot_tier" not in captured["system_prompt"]
    assert "You are MomoBot Max" in captured["system_prompt"]
    assert "<subagent_system>\n" in captured["system_prompt"]  # it can delegate (the block itself, not its mention in the preamble)


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["client", "exec", "admin"])
async def test_the_tool_ceiling_holds_for_every_role_that_runs_it(monkeypatch, tmp_path, role):
    _, captured = await _assemble(monkeypatch, tmp_path, role=role, app=_app_config(authorization=example_authorization()), keys=("c-max",))

    names = {t.name for t in captured["tools"]}
    staff_tools = {"propose_action"} if role != "client" else set()
    assert names <= set(MOMOBOT_MAX_TOOL_NAMES) | staff_tools
    assert ("propose_action" in names) is (role != "client")
    assert {"bash", "update_agent", "memory_search", "client_mcp_tool", "list_uploaded_files"}.isdisjoint(names)
    assert {"web_search", "web_fetch", "task", "present_files"} <= {t.name for t in captured["tools"]}


@pytest.mark.asyncio
async def test_the_ceiling_holds_even_with_authorization_off(monkeypatch, tmp_path):
    _, captured = await _assemble(monkeypatch, tmp_path, role="client", app=_app_config(), keys=("c-max",))

    assert {t.name for t in captured["tools"]} == set(MOMOBOT_MAX_TOOL_NAMES) - {"tool_search"}  # tool_search is added later by deferred-tool assembly


@pytest.mark.asyncio
async def test_a_clients_assignment_picks_the_effort(monkeypatch, tmp_path):
    created, _ = await _assemble(monkeypatch, tmp_path, role="client", app=_app_config(authorization=example_authorization()), keys=("acme-dental", "c-1"))

    assert created["reasoning_effort"] == "medium"


@pytest.mark.asyncio
async def test_a_base_client_run_is_the_light_momobot_chat(monkeypatch, tmp_path):
    created, captured = await _assemble(monkeypatch, tmp_path, role="client", app=_app_config(authorization=example_authorization()), keys=("not-unlocked",))

    assert (created["name"], created["thinking_enabled"], created["reasoning_effort"]) == ("claude-haiku-5-5", False, "medium")
    assert '<momobot_tier tier="base">' in captured["system_prompt"] and "Introduce yourself as MomoBot, not MomoBot Max" in captured["system_prompt"]
    assert "<subagent_system>\n" not in captured["system_prompt"]  # no subagent team on the base subscription
    # (The harness offers every tool, so the task tool's absence is the policy's subagent_enabled=False, tested there.)
    assert {t.name for t in captured["tools"]} <= set(MOMOBOT_MAX_TOOL_NAMES)
