"""Client/staff memory admission on the embedded Gateway's authenticated context."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, SystemMessage
from langgraph.graph.message import add_messages
from langgraph.runtime import Runtime

from app.gateway.services import inject_authenticated_user_context
from deerflow.agents.memory import admission, summarization_hook
from deerflow.agents.memory import tools as memory_tools
from deerflow.agents.memory.backends.deermem.deer_mem import DeerMem
from deerflow.agents.memory.backends.deermem.deermem.core.storage import create_empty_memory
from deerflow.agents.middlewares import memory_middleware
from deerflow.agents.middlewares.dynamic_context_middleware import DynamicContextMiddleware
from deerflow.agents.middlewares.summarization_middleware import SummarizationEvent
from deerflow.config import builtin_agents
from deerflow.config.memory_config import MemoryConfig
from deerflow.runtime.context_keys import CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY
from deerflow.runtime.runs.worker import _build_runtime_context


def _runtime(role, workspace="synthetic-workspace"):
    # Both request carriers try to grant staff authority and memory access.
    forged = {"user_role": "admin", "memory_enabled": True, "storage_user_id": "forged", "organization_role": "owner"}
    config = {"context": dict(forged), "configurable": dict(forged)}
    request = SimpleNamespace(
        state=SimpleNamespace(
            auth_source="session",
            user=SimpleNamespace(id=f"synthetic-{role}", system_role=role),
            actor_user_id=f"synthetic-{role}",
            storage_user_id=workspace,
            organization_id="synthetic-organization",
            organization_role="owner",
        )
    )
    inject_authenticated_user_context(config, request)
    context = _build_runtime_context("synthetic-thread", "synthetic-run", config["context"])
    assert context["user_role"] == role
    assert context["storage_user_id"] == workspace
    # The embedded worker supplies Runtime.context, without LangGraph auth user.
    runtime = Runtime(context=context)
    assert getattr(runtime, "server_info", None) is None
    return runtime


@pytest.mark.parametrize("role", ["client", "ambient-client", "admin", "exec"])
@pytest.mark.parametrize(
    ("tool_name", "arguments", "operation"),
    [
        ("memory_search_tool", {"query": "synthetic"}, "search"),
        ("memory_add_tool", {"content": "synthetic preference"}, "create_fact"),
        ("memory_update_tool", {"fact_id": "synthetic-fact", "content": "updated"}, "update_fact"),
        ("memory_delete_tool", {"fact_id": "synthetic-fact"}, "delete_fact"),
    ],
)
def test_explicit_memory_tools_obey_server_role(monkeypatch, role, tool_name, arguments, operation):
    runtime = _runtime("admin" if role == "ambient-client" else role)
    runtime.context["agent_name"] = "momobot-max"
    if role == "ambient-client":
        monkeypatch.setattr(admission, "get_current_user", lambda: SimpleNamespace(system_role="client"))
    manager = SimpleNamespace(search=Mock(return_value=[]), get_memory=Mock(return_value={"facts": []}), create_fact=Mock(return_value=({}, "synthetic-fact")), update_fact=Mock(), delete_fact=Mock())
    get_manager = Mock(return_value=manager)
    monkeypatch.setattr(memory_tools, "get_memory_manager", get_manager)

    result = json.loads(getattr(memory_tools, tool_name).func(runtime, **arguments))

    if role in {"client", "ambient-client"}:
        assert "error" in result
        get_manager.assert_not_called()
    else:
        assert "error" not in result
        operation_mock = getattr(manager, operation)
        operation_mock.assert_called_once()
        assert operation_mock.call_args.kwargs["user_id"] == "synthetic-workspace"
        assert operation_mock.call_args.kwargs["agent_name"] == "momobot-max"


@pytest.mark.parametrize(
    ("role", "workspace", "recalls"),
    [("client", "synthetic-workspace", False), ("admin", "synthetic-workspace", True), ("exec", "synthetic-workspace", True), ("admin", "other-workspace", False)],
)
def test_builtin_workspace_recall_obeys_server_role(tmp_path, monkeypatch, role, workspace, recalls):
    backend_config = {"storage_path": str(tmp_path), "token_counting": "char"}
    memory = create_empty_memory()
    marker = "SYNTHETIC_STAFF_ONLY_FACT"
    summary = "SYNTHETIC_STAFF_ONLY_SUMMARY"
    memory["facts"] = [{"id": "synthetic-fact", "content": marker, "confidence": 0.99}]
    memory["user"]["workContext"]["summary"] = summary
    storage = DeerMem(backend_config=backend_config)._storage
    summary_memory = create_empty_memory()
    summary_memory["user"]["workContext"]["summary"] = summary
    storage.save(summary_memory, user_id="synthetic-workspace")
    storage.save(memory, "momobot-max", user_id="synthetic-workspace")
    # Reload from disk so a process-local cache cannot explain the result.
    manager = DeerMem(backend_config=backend_config)
    monkeypatch.setattr("deerflow.agents.memory.get_memory_manager", lambda: manager)
    monkeypatch.setattr(builtin_agents, "_momobot_max_model", lambda: "synthetic-model")
    agent = builtin_agents.get_builtin_agent_config("momobot-max")
    assert agent.memory_enabled is True
    reader = DynamicContextMiddleware(agent_name=agent.name, app_config=SimpleNamespace(memory=MemoryConfig(enabled=True, token_counting="char")), memory_enabled=agent.memory_enabled)

    update = reader.before_agent({"messages": [HumanMessage(content="hello", id="latest")]}, _runtime(role, workspace))
    rendered = "\n".join(str(message.content) for message in update["messages"])

    assert (marker in rendered) is recalls
    assert (summary in rendered) is recalls
    assert "<current_date>" in rendered


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["client", "admin", "exec"])
@pytest.mark.parametrize("path", ["sync", "async", "compaction"])
async def test_workspace_memory_capture_obeys_server_role(monkeypatch, role, path):
    manager = SimpleNamespace(add=Mock(), aadd=AsyncMock(), add_nowait=Mock())
    get_manager = Mock(return_value=manager)
    monkeypatch.setattr(memory_middleware, "get_memory_manager", get_manager)
    monkeypatch.setattr(summarization_hook, "get_memory_manager", get_manager)
    monkeypatch.setattr(summarization_hook, "get_memory_config", lambda: MemoryConfig(enabled=True))
    runtime = _runtime(role)
    messages = [HumanMessage(content="Remember a synthetic preference"), AIMessage(content="Understood")]
    middleware = memory_middleware.MemoryMiddleware(agent_name="momobot-max", memory_config=MemoryConfig(enabled=True))

    if path == "compaction":
        summarization_hook.memory_flush_hook(SummarizationEvent(tuple(messages), (), "synthetic-thread", "momobot-max", runtime))
        capture = manager.add_nowait
    elif path == "async":
        await middleware.aafter_agent({"messages": messages}, runtime)
        capture = manager.aadd
    else:
        middleware.after_agent({"messages": messages}, runtime)
        capture = manager.add

    if role == "client":
        get_manager.assert_not_called()
        capture.assert_not_called()
    else:
        capture.assert_called_once()
        assert capture.call_args.kwargs["user_id"] == "synthetic-workspace"
        assert capture.call_args.kwargs["agent_name"] == "momobot-max"


@pytest.mark.asyncio
@pytest.mark.parametrize("async_path", [False, True])
async def test_client_discards_frozen_memory_but_keeps_date_and_user_messages(async_path):
    reader = DynamicContextMiddleware()
    frozen = reader._make_reminder_and_user_messages(HumanMessage(content="earlier", id="old"), reader._build_date_update_reminder(), "SYNTHETIC_FROZEN_STAFF_MEMORY")
    messages = [*frozen, HumanMessage(content="latest question", id="latest")]
    runtime = _runtime("client")
    runtime.context[CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY] = {message.id for message in messages}

    update = await reader.abefore_agent({"messages": messages}, runtime) if async_path else reader.before_agent({"messages": messages}, runtime)

    assert update is not None
    assert [message.id for message in update["messages"] if isinstance(message, RemoveMessage)] == ["old__memory"]
    remaining = add_messages(messages, update["messages"])
    assert any(isinstance(message, SystemMessage) and "<current_date>" in message.content for message in remaining)
    assert [message.content for message in remaining if isinstance(message, HumanMessage)] == ["earlier", "latest question"]
    assert reader._effective_memory_message_for_request(messages, runtime) is None
