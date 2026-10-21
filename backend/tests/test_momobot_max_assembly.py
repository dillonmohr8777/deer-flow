"""What a MomoBot Max run is actually assembled from: model, effort, tools, delegation and instructions."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

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
    app = AppConfig.model_validate({**example.model_dump(), "models": [model], "momobot_max": {"enabled": True, "default_effort": "high", "client_effort": {"vhin-cares": "medium"}}, **extra})
    app.summarization.enabled = False
    return app


async def _assemble(monkeypatch, tmp_path, *, role: str, app: AppConfig, keys=()):
    import deerflow.tools
    from deerflow.agents.lead_agent import agent, prompt

    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    set_app_config(app)  # the built-in agent reads the process-wide config, like production

    async def client_keys(_user_id):
        return keys

    monkeypatch.setattr("app.gateway.momobot_max.client_keys_for_user", client_keys)
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
    try:
        agent._assemble_lead_agent(config, app_config=app)
    finally:
        reset_app_config()
    return created, captured


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["client", "exec", "admin"])
async def test_a_momobot_max_run_has_the_models_effort_delegation_and_soul(monkeypatch, tmp_path, role):
    created, captured = await _assemble(monkeypatch, tmp_path, role=role, app=_app_config(authorization=example_authorization()))

    assert (created["name"], created["thinking_enabled"], created["reasoning_effort"]) == ("claude-opus-5-5", True, "high")
    assert "You are MomoBot Max" in captured["system_prompt"]
    assert "<subagent_system>" in captured["system_prompt"]  # it can delegate


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["client", "exec", "admin"])
async def test_the_tool_ceiling_holds_for_every_role_that_runs_it(monkeypatch, tmp_path, role):
    _, captured = await _assemble(monkeypatch, tmp_path, role=role, app=_app_config(authorization=example_authorization()))

    assert {t.name for t in captured["tools"]} <= set(MOMOBOT_MAX_TOOL_NAMES)
    assert {"bash", "update_agent", "propose_action", "memory_search", "client_mcp_tool", "list_uploaded_files"}.isdisjoint(t.name for t in captured["tools"])
    assert {"web_search", "web_fetch", "task", "present_files"} <= {t.name for t in captured["tools"]}


@pytest.mark.asyncio
async def test_the_ceiling_holds_even_with_authorization_off(monkeypatch, tmp_path):
    _, captured = await _assemble(monkeypatch, tmp_path, role="client", app=_app_config())

    assert {t.name for t in captured["tools"]} == set(MOMOBOT_MAX_TOOL_NAMES) - {"tool_search"}  # tool_search is added later by deferred-tool assembly


@pytest.mark.asyncio
async def test_a_clients_assignment_picks_the_effort(monkeypatch, tmp_path):
    created, _ = await _assemble(monkeypatch, tmp_path, role="client", app=_app_config(authorization=example_authorization()), keys=("vhin-cares", "c-1"))

    assert created["reasoning_effort"] == "medium"
