"""Regression tests for recording the model a run actually executes on."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

from app.gateway.auth_disabled import AUTH_SOURCE_INTERNAL
from app.gateway.run_models import RunCreateRequest
from app.gateway.services import start_run
from deerflow.agents.lead_agent.agent import LeadAgentAssembly
from deerflow.config.agents_config import AgentConfig
from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config
from deerflow.persistence.thread_meta.memory import MemoryThreadMetaStore
from deerflow.runtime import RunManager
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.runs.store.memory import MemoryRunStore
from deerflow.runtime.runs.worker import RunContext, run_agent

WORKER_MODEL = "worker-client"
AGENT_MODEL = "agent-model"


@pytest.fixture
def _model_app_config():
    prices = {name: {"input_per_mtok": 0, "output_per_mtok": 0} for name in (WORKER_MODEL, AGENT_MODEL)}
    set_app_config(
        AppConfig.model_validate(
            {
                "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
                "models": [
                    {"name": WORKER_MODEL, "use": "langchain_openai:ChatOpenAI", "model": WORKER_MODEL},
                    {"name": AGENT_MODEL, "use": "langchain_openai:ChatOpenAI", "model": AGENT_MODEL},
                ],
                "cost_router": {
                    "enabled": True,
                    "default_route": "default",
                    "routes": {"default": {"model": WORKER_MODEL}},
                    "prices": prices,
                    "denylist": [],
                },
            }
        )
    )
    try:
        yield
    finally:
        reset_app_config()


def _request(run_manager: RunManager, *, auth_source: str | None = AUTH_SOURCE_INTERNAL):
    store = InMemoryStore()
    return SimpleNamespace(
        headers={},
        state=SimpleNamespace(auth_source=auth_source),
        app=SimpleNamespace(
            state=SimpleNamespace(
                stream_bridge=SimpleNamespace(),
                run_manager=run_manager,
                checkpointer=InMemorySaver(),
                store=store,
                run_event_store=MemoryRunEventStore(),
                run_events_config=None,
                thread_store=MemoryThreadMetaStore(store),
            )
        ),
    )


@pytest.mark.asyncio
async def test_scheduled_custom_agent_run_records_agent_model_not_cost_route(_model_app_config):
    run_store = MemoryRunStore()
    run_manager = RunManager(store=run_store)
    request = _request(run_manager)
    scheduled_body = RunCreateRequest(
        assistant_id="always-on-drafts",
        input={"messages": [{"role": "user", "content": "draft the scheduled update"}]},
        metadata={"scheduled_task_id": "task-1", "scheduled_task_run_id": "occurrence-1"},
        config={"recursion_limit": 100},
        context={"non_interactive": True, "user_id": "owner-1"},
        multitask_strategy="reject",
        on_disconnect="continue",
    )
    load_agent = AsyncMock(return_value=AgentConfig(name="always-on-drafts", model=AGENT_MODEL))

    with (
        patch("app.gateway.services._load_scope_agent_config", new=load_agent),
        patch("app.gateway.services.resolve_agent_factory", return_value=object()),
        patch("app.gateway.services.run_agent", new=AsyncMock()),
    ):
        record = await start_run(scheduled_body, "thread-scheduled-effective-model", request)
        await record.task

    assert record.model_name == AGENT_MODEL
    stored = await run_store.get(record.run_id)
    assert stored is not None
    assert stored["model_name"] == AGENT_MODEL


@pytest.mark.asyncio
async def test_slack_agent_config_unknown_model_is_rejected_before_run_creation(_model_app_config):
    run_store = MemoryRunStore()
    run_manager = RunManager(store=run_store)
    request = _request(run_manager)
    slack_body = RunCreateRequest(
        assistant_id="lead_agent",
        input={"messages": [{"role": "user", "content": "hello from slack"}]},
        context={"agent_name": "slack-agent", "channel_name": "slack"},
    )
    load_agent = AsyncMock(return_value=AgentConfig(name="slack-agent", model="removed-model"))
    worker = AsyncMock()

    with (
        patch("app.gateway.services._load_scope_agent_config", new=load_agent),
        patch("app.gateway.services.resolve_agent_factory", return_value=object()),
        patch("app.gateway.services.run_agent", new=worker),
        pytest.raises(HTTPException) as error,
    ):
        await start_run(slack_body, "thread-slack-unknown-agent-model", request)

    assert error.value.status_code == 422
    assert "removed-model" in str(error.value.detail)
    assert "slack-agent" in str(error.value.detail)
    assert await run_manager.list_by_thread("thread-slack-unknown-agent-model", user_id=None) == []
    worker.assert_not_awaited()


class _GraphWithoutMetadata:
    checkpointer = None
    store = None
    interrupt_before_nodes = None
    interrupt_after_nodes = None

    async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
        del graph_input, config, stream_mode, subgraphs
        yield {"messages": []}


@pytest.mark.anyio
async def test_worker_records_effective_model_from_lead_assembly_without_graph_metadata():
    run_store = MemoryRunStore()
    run_manager = RunManager(store=run_store)
    record = await run_manager.create_or_reject(
        "thread-worker-effective-model",
        assistant_id="always-on-drafts",
        model_name=WORKER_MODEL,
    )
    bridge = SimpleNamespace(
        publish=AsyncMock(),
        publish_end=AsyncMock(),
        cleanup=AsyncMock(),
    )

    def factory(*, config, **_kwargs):
        # Mirrors _assemble_lead_agent: the effective model is stamped on the
        # runnable config, while the compiled graph itself has no .metadata.
        config.setdefault("metadata", {})["model_name"] = AGENT_MODEL
        return LeadAgentAssembly(graph=_GraphWithoutMetadata(), descriptor=None)

    await run_agent(
        bridge,
        run_manager,
        record,
        ctx=RunContext(checkpointer=None, event_store=MemoryRunEventStore()),
        agent_factory=factory,
        graph_input={"messages": []},
        config={},
    )

    assert record.model_name == AGENT_MODEL
    stored = await run_store.get(record.run_id)
    assert stored is not None
    assert stored["model_name"] == AGENT_MODEL
