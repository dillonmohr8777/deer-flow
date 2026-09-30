"""Tests for scheduling the CEO Desk daily-digest sweep (queue item e14).

``deerflow.ceo_desk.digest.run_ceo_desk_digest`` already knows whether and
how to generate one organization's digest (see ``test_ceo_desk_digest.py``
for that accept bar); this file covers the scheduling half, mirroring
``test_seat_scorecard_enforcement.py``: the Gateway lifespan registers a
recurring sweep when configured, never by default or against an
unconfigured test double, and each organization's digest lands only in its
own storage context.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from org_isolation_fixtures import ORG_A, ORG_B, USER_A, USER_B, acting_as, org_world  # noqa: F401

_ET = ZoneInfo("America/New_York")


async def _stub_generate(_window, **_kwargs):
    return "Steady day, nothing on fire."


@pytest.mark.asyncio
async def test_sweep_generates_each_organizations_digest_in_its_own_context(org_world, monkeypatch):  # noqa: F811
    from app.gateway import app as app_module
    from app.gateway.app import _run_ceo_desk_digest_sweep
    from deerflow.ceo_desk import digest as digest_module
    from deerflow.config.ceo_desk_config import CeoDeskConfig
    from deerflow.persistence.ceo_desk import CeoDeskDigestRepository

    monkeypatch.setattr(digest_module, "generate_daily_digest", _stub_generate)
    monkeypatch.setattr(app_module, "get_app_config", lambda: SimpleNamespace(ceo_desk=CeoDeskConfig()))

    # Fixed, well past the default 08:00 ET digest_hour_et so the sweep is
    # due regardless of what time this test happens to run.
    due_now = datetime(2026, 3, 15, 9, 0, tzinfo=_ET)
    await _run_ceo_desk_digest_sweep(now=due_now)

    with acting_as(USER_A, ORG_A):
        latest_a = await CeoDeskDigestRepository(org_world).latest_digest()
    with acting_as(USER_B, ORG_B):
        latest_b = await CeoDeskDigestRepository(org_world).latest_digest()

    assert latest_a is not None
    assert latest_b is not None
    assert latest_a["organization_id"] == ORG_A
    assert latest_b["organization_id"] == ORG_B


@pytest.mark.asyncio
async def test_ceo_desk_digest_loop_starts_when_enabled():
    import asyncio

    from app.gateway.app import _start_ceo_desk_digest_loop
    from deerflow.config.ceo_desk_config import CeoDeskConfig

    startup_config = SimpleNamespace(ceo_desk=CeoDeskConfig(digest_enabled=True, digest_check_interval_seconds=60))
    task = _start_ceo_desk_digest_loop(startup_config)
    try:
        assert task is not None
        assert not task.done()
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_ceo_desk_digest_loop_does_not_start_by_default():
    from app.gateway.app import _start_ceo_desk_digest_loop
    from deerflow.config.ceo_desk_config import CeoDeskConfig

    assert _start_ceo_desk_digest_loop(SimpleNamespace(ceo_desk=CeoDeskConfig())) is None


def test_ceo_desk_digest_loop_does_not_start_against_an_unconfigured_test_double():
    """A bare SimpleNamespace/MagicMock startup_config (most existing lifespan tests) must never start it."""
    from unittest.mock import MagicMock

    from app.gateway.app import _start_ceo_desk_digest_loop

    assert _start_ceo_desk_digest_loop(SimpleNamespace()) is None
    assert _start_ceo_desk_digest_loop(MagicMock()) is None


@pytest.mark.asyncio
async def test_lifespan_registers_the_ceo_desk_digest_loop_when_enabled():
    import asyncio as _asyncio
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock, MagicMock, patch

    from fastapi import FastAPI

    from app.gateway.app import lifespan
    from deerflow.config.ceo_desk_config import CeoDeskConfig

    @asynccontextmanager
    async def _noop_langgraph_runtime(_app, _startup_config):
        yield

    app = FastAPI()
    startup_config = SimpleNamespace(
        log_level="INFO",
        memory=SimpleNamespace(enabled=False, shutdown_flush_timeout_seconds=5.0),
        ceo_desk=CeoDeskConfig(digest_enabled=True, digest_check_interval_seconds=3600),
    )
    fake_service = MagicMock()
    fake_service.get_status.return_value = {}

    async def fake_start(_startup_config, **_kwargs):
        return fake_service

    with (
        patch("app.gateway.app.get_app_config", return_value=startup_config),
        patch("app.gateway.app.get_gateway_config", return_value=MagicMock(host="x", port=0)),
        patch("app.gateway.app.langgraph_runtime", _noop_langgraph_runtime),
        patch("app.gateway.app.auth.close_oidc_service", AsyncMock()),
        patch("app.channels.service.start_channel_service", side_effect=fake_start),
        patch("app.channels.service.stop_channel_service", AsyncMock()),
        patch("deerflow.skills.projection.ensure_public_skill_projection"),
        patch("deerflow.agents.memory.get_memory_manager", return_value=MagicMock()),
    ):
        async with lifespan(app):
            task = app.state.ceo_desk_digest_loop_task
            assert task is not None
            assert not task.done()

        assert task.done()
        assert task.cancelled()

    await _asyncio.sleep(0)
