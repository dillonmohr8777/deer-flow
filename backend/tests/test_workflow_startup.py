"""Actual Gateway lifespan wires and drains the workflow feature on its shared runtime."""

import json
import sqlite3
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from langgraph.checkpoint.memory import InMemorySaver
from test_workflow_native_runtime import NATIVE_OWNER, SyntheticAdapter, create, drain, runtime

from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.config.mcp_tasks_config import McpTasksConfig

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("enabled", [False, True, "legacy"])
async def test_gateway_lifespan_uses_shared_native_components_and_closes_workflow_before_runtime(tmp_path, monkeypatch, enabled):
    from app.gateway.app import lifespan

    monkeypatch.setenv("MOMOBOT_WORKFLOWS_ENABLED", "true" if enabled else "false")
    monkeypatch.setenv("MOMOBOT_OPENAI_AGENTS_ENABLED", "false")
    monkeypatch.setenv("MOMOBOT_BROWSERBASE_ENABLED", "false")
    app = FastAPI()
    store, events, manager, threads = runtime()
    saver = InMemorySaver()
    adapter = SyntheticAdapter()
    observations = []

    @asynccontextmanager
    async def native_runtime(application, _configuration):
        application.state.checkpointer = saver
        application.state.run_manager = manager
        application.state.thread_store = threads
        application.state.run_event_store = events
        try:
            yield
        finally:
            service = getattr(application.state, "workflow_service", None)
            observations.append(service is None or not service.started and service.lease is None and not service.tasks)

    configuration = MagicMock()
    configuration.log_level = "INFO"
    configuration.memory.enabled = False
    configuration.scheduler.enabled = False
    configuration.mcp_tasks = McpTasksConfig()
    memory = MagicMock()
    memory.warm.return_value = None
    channel = SimpleNamespace(get_status=lambda: {})
    monkeypatch.setattr("app.gateway.app.get_app_config", lambda: configuration)
    monkeypatch.setattr("app.gateway.app.get_gateway_config", lambda: SimpleNamespace(host="127.0.0.1", port=0))
    monkeypatch.setattr("app.gateway.app.langgraph_runtime", native_runtime)
    monkeypatch.setattr("app.gateway.app._ensure_admin_user", AsyncMock())
    monkeypatch.setattr("app.gateway.app._run_startup_trash_sweep", AsyncMock())
    monkeypatch.setattr("app.gateway.app.cleanup_stale_upload_staging_files", lambda: 0)
    monkeypatch.setattr("app.gateway.app.ensure_browser_runtime_available", lambda configuration: None)
    monkeypatch.setattr("app.gateway.app.setup_monocle_tracing_if_enabled", lambda: None)
    monkeypatch.setattr("deerflow.skills.projection.ensure_public_skill_projection", lambda **kwargs: False)
    monkeypatch.setattr("deerflow.agents.memory.get_memory_manager", lambda: memory)
    monkeypatch.setattr("app.channels.service.start_channel_service", AsyncMock(return_value=channel))
    monkeypatch.setattr("app.channels.service.stop_channel_service", AsyncMock())
    monkeypatch.setattr("app.gateway.app.auth.close_oidc_service", AsyncMock())
    monkeypatch.setattr("deerflow.community.browser_automation.get_browser_session_manager", lambda: SimpleNamespace(close_all_sessions=AsyncMock(return_value=0)))
    monkeypatch.setattr(ExtensionsConfig, "from_file", lambda: ExtensionsConfig())
    monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: SimpleNamespace(base_dir=tmp_path))
    monkeypatch.setattr("app.gateway.workflow_adapters.WorkflowModelAdapter", lambda: adapter)
    monkeypatch.setattr("app.gateway.workflow_authority.workflow_actor_authorized", AsyncMock(return_value=True))

    if enabled == "legacy":
        from app.gateway.workflow_service import WorkflowService

        prior = WorkflowService(tmp_path / "workflows.sqlite", checkpointer=saver, adapter=adapter, run_manager=manager, thread_store=threads, event_store=events)
        await prior.start()
        admitted = await create(prior)
        await drain(prior)
        await prior.aclose()
        with sqlite3.connect(tmp_path / "workflows.sqlite") as connection:
            data = json.loads(connection.execute("SELECT data FROM workflow_jobs WHERE id=?", (admitted["id"],)).fetchone()[0])
            data.pop("_native_storage_user")
            connection.execute("UPDATE workflow_jobs SET data=? WHERE id=?", (json.dumps(data), admitted["id"]))
        with pytest.raises(RuntimeError, match="workflow_native_namespace_migration_required"):
            async with lifespan(app):
                pytest.fail("Legacy shared native journal reached Gateway serving state")
        assert len(adapter.calls) == 3 and observations == [True]
        return

    async with lifespan(app):
        service = getattr(app.state, "workflow_service", None)
        if enabled:
            assert service.started is True
            assert service.checkpointer is saver and service.run_manager is manager
            assert service.thread_store is threads and service.event_store is events
            assert service.path == tmp_path / "workflows.sqlite"
            admitted = await create(service)
            await drain(service)
            result = await service.snapshot("synthetic-owner-scope", admitted["id"])
            assert result["status"] == "completed" and result["accepted"] is True
            assert await store.get(result["native_run_id"], user_id=NATIVE_OWNER) is not None
        else:
            assert service is None
            assert not (tmp_path / "workflows.sqlite").exists()
            assert not adapter.calls
    assert observations == [True]
