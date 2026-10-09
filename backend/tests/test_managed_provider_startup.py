"""Disabled managed providers must not restrict ordinary Gateway workers."""

from __future__ import annotations

import sys
from contextlib import ExitStack, asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI

from app.gateway.authz import AuthContext
from app.gateway.browserbase_service import BrowserbaseResearchService
from app.gateway.routers import browserbase_research, openai_agents
from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.config.paths import Paths


@asynccontextmanager
async def _ordinary_runtime(_app, _config):
    """Provider startup is independent of the ordinary runtime's database."""
    yield


def _worker() -> FastAPI:
    worker = FastAPI()

    @worker.middleware("http")
    async def identity(request, call_next):
        request.state.auth = AuthContext(
            user=SimpleNamespace(id="me", system_role="admin"),
            permissions=["runs:read", "runs:create", "runs:cancel"],
            organization_id="private-organization",
            actor_user_id="me",
            storage_user_id="me",
        )
        return await call_next(request)

    worker.include_router(browserbase_research.router)
    worker.include_router(openai_agents.router)
    return worker


@pytest.mark.asyncio
@pytest.mark.parametrize("fcntl_unavailable", [False, True], ids=["shared-workers", "windows-base"])
async def test_disabled_providers_allow_overlapping_gateway_workers_without_storage(monkeypatch, tmp_path, fcntl_unavailable):
    """Exercise the real lifespan, lazy API accessors, and rejected admissions."""
    from app.gateway.app import lifespan

    monkeypatch.setenv("MOMOBOT_BROWSERBASE_ENABLED", "false")
    monkeypatch.setenv("MOMOBOT_OPENAI_AGENTS_ENABLED", "false")
    # Existing credentials must not turn an explicitly disabled lane on.
    monkeypatch.setenv("BROWSERBASE_API_KEY", "offline-test-key")
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test-key")
    if fcntl_unavailable:
        monkeypatch.setitem(sys.modules, "fcntl", None)

    provider_requests = AsyncMock(side_effect=AssertionError("Disabled provider must not contact the network"))
    monkeypatch.setattr(BrowserbaseResearchService, "_request", provider_requests)
    home = tmp_path / "provider-home"
    paths = Paths(home)
    config = SimpleNamespace(
        log_level="INFO",
        memory=SimpleNamespace(token_counting="char", enabled=False, shutdown_flush_timeout_seconds=5.0),
    )
    channel = MagicMock()
    channel.get_status.return_value = {}
    memory = MagicMock()
    memory.warm.return_value = None
    first, second = _worker(), _worker()

    patches = (
        patch("app.gateway.app.get_app_config", return_value=config),
        patch("app.gateway.app.get_gateway_config", return_value=SimpleNamespace(host="127.0.0.1", port=0)),
        patch("app.gateway.app.configure_logging"),
        patch("app.gateway.app.ensure_browser_runtime_available"),
        patch("app.gateway.app.setup_monocle_tracing_if_enabled"),
        patch("app.gateway.app.langgraph_runtime", _ordinary_runtime),
        patch("app.gateway.app._ensure_admin_user", AsyncMock()),
        patch("app.gateway.app._run_startup_trash_sweep", AsyncMock()),
        patch("app.gateway.app.cleanup_stale_upload_staging_files", return_value=0),
        patch("app.gateway.app._shutdown_memory_backend", AsyncMock()),
        patch("app.gateway.app.auth.close_oidc_service", AsyncMock()),
        patch("app.channels.service.start_channel_service", AsyncMock(return_value=channel)),
        patch("app.channels.service.stop_channel_service", AsyncMock()),
        patch("deerflow.skills.projection.ensure_public_skill_projection", return_value=False),
        patch("deerflow.agents.memory.get_memory_manager", return_value=memory),
        patch("deerflow.config.extensions_config.ExtensionsConfig.from_file", return_value=ExtensionsConfig()),
        patch("deerflow.community.browser_automation.get_browser_session_manager", return_value=SimpleNamespace(close_all_sessions=AsyncMock(return_value=0))),
        patch("deerflow.config.paths.get_paths", return_value=paths),
        patch.object(browserbase_research, "get_paths", return_value=paths),
        patch.object(openai_agents, "get_paths", return_value=paths),
    )
    with ExitStack() as stack:
        for context in patches:
            stack.enter_context(context)
        # Both worker lifespans overlap against the same provider paths, as
        # legitimate ordinary-runtime Postgres workers would on one host.
        async with lifespan(first), lifespan(second):
            for worker in (first, second):
                assert getattr(worker.state, "browserbase_service", None) is None
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=worker), base_url="http://gateway.test") as client:
                    browser = await client.get("/api/browserbase/status", headers={"X-Expected-User-Id": "me"})
                    agents = await client.get("/api/openai-agents/status", headers={"X-Expected-User-Id": "me"})
                    assert browser.status_code == agents.status_code == 200
                    assert browser.json()["reason"] == agents.json()["reason"] == "not_enabled"
                    assert browser.json()["available"] is agents.json()["available"] is False
                    assert agents.json()["configured"] is True

                    headers = {"X-Expected-Browserbase-Scope": browser.json()["owner_scope"], "Idempotency-Key": "disabled-request"}
                    create = await client.post("/api/browserbase/research", headers=headers, json={"urls": ["https://example.com"], "title": "Disabled"})
                    listing = await client.get("/api/browserbase/research", headers=headers)
                    assert create.status_code == listing.status_code == 503
                    assert create.json()["detail"] == listing.json()["detail"] == "not_enabled"

                    agent_create = await client.post(
                        "/api/openai-agents/sessions",
                        headers={"X-Expected-Agent-Scope": agents.json()["owner_scope"], "Idempotency-Key": "disabled-agent"},
                        json={"input": "Must remain disabled"},
                    )
                    assert agent_create.status_code == 503
                    assert agent_create.json()["detail"] == "openai_agents_unavailable"
                    assert worker.state.browserbase_service.started is False
                    assert worker.state.browserbase_service.lease is None
                    assert worker.state.openai_agent_service._watchdog is None
                    assert not home.exists()

    provider_requests.assert_not_awaited()
    assert not home.exists(), "Disabled startup, requests, and shutdown must leave provider storage untouched"
