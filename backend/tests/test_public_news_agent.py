"""Public-news assembly keeps tool guards and excludes owner context."""

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
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
    persona = AgentConfig(name="ai-tech-news", tool_names=["web_search", "web_fetch"], memory_enabled=False, self_update_enabled=False, skills=[], mcp_plugins=[], allowed_subagents=[])
    assert persona.knowledge_scope is None
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
    # Exercise the actual Gateway admission boundary, not a hand-built factory
    # config: runtime-only keys must survive an authenticated internal caller.
    from app.gateway.services import merge_run_context_overrides

    body_context = {"public_news_channel": True, "channel_name": "slack", "agent_name": "ai-tech-news", "user_id": "synthetic-owner", "subagent_enabled": True, "is_plan_mode": True}
    config = {}
    merge_run_context_overrides(config, body_context, internal=True)
    assert config["context"]["public_news_channel"] is True
    assert "public_news_channel" not in config["configurable"]
    assembly = agent._assemble_lead_agent(config, app_config=app)
    assert {t.name for t in captured["tools"]} == {"web_search", "web_fetch"}
    assert set(assembly.graph.nodes["tools"].bound.tools_by_name) == {"web_search", "web_fetch"}
    names = {type(m).__name__ for m in captured["middleware"]}
    assert "SkillToolPolicyMiddleware" in names
    ceiling = next(m for m in captured["middleware"] if type(m).__name__ == "SkillToolPolicyMiddleware")
    for forbidden in dangerous:
        request = SimpleNamespace(tool_call={"name": forbidden, "id": "synthetic-call", "args": {}}, state={}, runtime=SimpleNamespace(context={}))
        denied = ceiling.wrap_tool_call(request, lambda request: pytest.fail("private tool executed"))
        assert denied.status == "error"
    assert not names & {"UploadsMiddleware", "DynamicContextMiddleware", "ClientCorrectionsMiddleware", "DurableContextMiddleware", "MemoryMiddleware", "SandboxMiddleware", "TodoMiddleware", "TitleMiddleware"}
    assert "PUBLIC_NEWS_PERSONA" in captured["system_prompt"]
    assert "<user_profile>" not in captured["system_prompt"]


def test_missing_public_agent_fails_closed(monkeypatch):
    from deerflow.agents.lead_agent import agent

    app = AppConfig.model_validate(yaml.safe_load((Path(__file__).parents[2] / "config.example.yaml").read_text()))
    monkeypatch.setattr(agent, "load_agent_config", lambda *a, **kw: None)
    with pytest.raises(ValueError, match="readback|provisioned"):
        agent._assemble_lead_agent({"context": {"public_news_channel": True, "agent_name": "ai-tech-news"}}, app_config=app)


@pytest.mark.parametrize("scope", [{"version": 1, "mode": "all"}, {"version": 1, "mode": "selected", "dataset_ids": ["synthetic-private-dataset"]}])
def test_public_news_private_enabled_knowledge_scope_fails_closed(monkeypatch, scope):
    from deerflow.agents.lead_agent import agent

    app = AppConfig.model_validate(yaml.safe_load((Path(__file__).parents[2] / "config.example.yaml").read_text()))
    persona = AgentConfig(name="ai-tech-news", tool_names=["web_search", "web_fetch"], memory_enabled=False, self_update_enabled=False, skills=[], mcp_plugins=[], allowed_subagents=[], knowledge_scope=scope)
    monkeypatch.setattr(agent, "load_agent_config", lambda *a, **kw: persona)
    monkeypatch.setattr(agent, "create_chat_model", lambda **kw: pytest.fail("model constructed before private scope rejection"))
    with pytest.raises(ValueError, match="disable private knowledge"):
        agent._assemble_lead_agent({"context": {"public_news_channel": True, "agent_name": "ai-tech-news"}}, app_config=app)


def test_gateway_admission_accepts_omitted_scope_without_provider_lookup(monkeypatch):
    from app.gateway import knowledge_scope_admission

    persona = AgentConfig(name="ai-tech-news", tool_names=["web_search", "web_fetch"], memory_enabled=False, self_update_enabled=False, skills=[], mcp_plugins=[], allowed_subagents=[])
    assert persona.knowledge_scope is None
    monkeypatch.setattr(knowledge_scope_admission, "assistant_supports_knowledge_scope", lambda **kw: pytest.fail("unneeded provider lookup rejects omitted scope"))
    message = HumanMessage(content="synthetic public news question")
    graph_input = {"messages": [message]}
    execution_scope = knowledge_scope_admission.admit_message_knowledge_scope(graph_input, assistant_id="lead_agent", app_config=SimpleNamespace(knowledge_base=SimpleNamespace(enabled=False)), agent_config=persona)
    assert execution_scope is None
    assert graph_input["messages"][0] is message
    assert "knowledge_scope" not in message.additional_kwargs


def test_external_public_news_flag_cannot_trigger_public_assembly():
    from app.gateway.services import merge_run_context_overrides, strip_internal_context_keys
    from deerflow.agents.lead_agent.agent import _get_runtime_config

    # HTTP callers can supply both legacy configurable keys and raw context.
    # The strip boundary must remove both before whitelisted body.context merge.
    config = {"configurable": {"public_news_channel": True}, "context": {"public_news_channel": True}}
    strip_internal_context_keys(config)
    merge_run_context_overrides(config, {"public_news_channel": True, "channel_name": "slack", "agent_name": "ai-tech-news"}, internal=False)
    assert "public_news_channel" not in config["configurable"]
    assert "public_news_channel" not in config["context"]
    assert "channel_name" not in config["context"]
    assert _get_runtime_config(config).get("public_news_channel") is not True
