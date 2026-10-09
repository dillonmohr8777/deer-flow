"""Public-news assembly keeps tool guards and excludes owner context."""

from pathlib import Path

import pytest
import yaml
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool

from deerflow.config.agents_config import AgentConfig
from deerflow.config.app_config import AppConfig
from deerflow.config.model_config import ModelConfig


class OfflineModel(BaseChatModel):
    @property
    def _llm_type(self):
        return "offline-public-news"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="offline fixture"))])


def test_public_news_assembly_has_only_public_tools_and_no_private_context(monkeypatch):
    import deerflow.tools
    from deerflow.agents.lead_agent import agent, prompt

    app = AppConfig.model_validate(yaml.safe_load((Path(__file__).parents[2] / "config.example.yaml").read_text()))
    app = AppConfig.model_validate({**app.model_dump(), "models": [ModelConfig(name="offline", use="langchain_openai:ChatOpenAI", model="offline").model_dump()]})
    app.summarization.enabled = False
    persona = AgentConfig(name="ai-tech-news", tool_names=["web_search", "web_fetch"], memory_enabled=False, self_update_enabled=False, skills=[], mcp_plugins=[], allowed_subagents=[], knowledge_scope={"version": 1, "mode": "disabled"})
    monkeypatch.setattr(agent, "load_agent_config", lambda *a, **kw: persona)
    monkeypatch.setattr(agent, "create_chat_model", lambda **kw: OfflineModel())
    monkeypatch.setattr(agent, "_resolve_model_name", lambda *a, **kw: app.models[0].name)
    monkeypatch.setattr(prompt, "get_agent_soul", lambda *a, **kw: "PUBLIC_NEWS_PERSONA")
    for name in ["_build_user_profile_section", "_build_acp_section", "_build_custom_mounts_section"]:
        monkeypatch.setattr(prompt, name, lambda *a, **kw: pytest.fail("private profile/catalog loaded"))

    def make(name):
        @tool(name)
        def fixture(query: str) -> str:
            """Return a synthetic public source."""
            return "public source"

        return fixture

    dangerous = ["update_agent", "read_file", "list_uploaded_files", "task", "knowledge_search", "client_mcp", "memory_search"]
    monkeypatch.setattr(deerflow.tools, "get_available_tools", lambda **kw: [make(n) for n in ["web_search", "web_fetch", *dangerous]])
    captured = {}
    real_create = agent.create_agent

    def capture(**kwargs):
        captured.update(kwargs)
        return real_create(**kwargs)

    monkeypatch.setattr(agent, "create_agent", capture)
    config = {"context": {"public_news_channel": True, "agent_name": "ai-tech-news", "user_id": "synthetic-owner", "subagent_enabled": True, "is_plan_mode": True}}
    assembly = agent._assemble_lead_agent(config, app_config=app)
    assert {t.name for t in captured["tools"]} == {"web_search", "web_fetch"}
    assert set(assembly.graph.nodes["tools"].bound.tools_by_name) == {"web_search", "web_fetch"}
    names = {type(m).__name__ for m in captured["middleware"]}
    assert "SkillToolPolicyMiddleware" in names
    assert not names & {"UploadsMiddleware", "DynamicContextMiddleware", "ClientCorrectionsMiddleware", "DurableContextMiddleware", "MemoryMiddleware", "SandboxMiddleware", "TodoMiddleware", "TitleMiddleware"}
    assert "PUBLIC_NEWS_PERSONA" in captured["system_prompt"]
    assert "<user_profile>" not in captured["system_prompt"]


def test_missing_public_agent_fails_closed(monkeypatch):
    from deerflow.agents.lead_agent import agent

    app = AppConfig.model_validate(yaml.safe_load((Path(__file__).parents[2] / "config.example.yaml").read_text()))
    monkeypatch.setattr(agent, "load_agent_config", lambda *a, **kw: None)
    with pytest.raises(ValueError, match="readback|provisioned"):
        agent._assemble_lead_agent({"context": {"public_news_channel": True, "agent_name": "ai-tech-news"}}, app_config=app)
