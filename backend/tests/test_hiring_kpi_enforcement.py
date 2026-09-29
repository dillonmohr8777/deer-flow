"""Tests for scheduling the weekly hire KPI-review sweep (queue item e12).

``deerflow.hiring.kpi_review.evaluate_all_hire_kpi_reviews`` already knows how
to judge/miss/retire a hire's weekly KPI (see ``test_hiring_kpi_review.py``
for that accept bar); this file covers the scheduling half, mirroring
``test_seat_scorecard_enforcement.py``'s loop-wiring tests: the Gateway
lifespan registers a recurring sweep when configured, and never does by
default or against an unconfigured test double.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_hire_kpi_review_loop_starts_when_enabled():
    import asyncio

    from app.gateway.app import _start_hire_kpi_review_loop
    from deerflow.config.hiring_config import HiringConfig

    startup_config = SimpleNamespace(hiring=HiringConfig(kpi_check_enabled=True, kpi_check_interval_seconds=60))
    task = _start_hire_kpi_review_loop(startup_config)
    try:
        assert task is not None
        assert not task.done()
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_hire_kpi_review_loop_does_not_start_by_default():
    from app.gateway.app import _start_hire_kpi_review_loop
    from deerflow.config.hiring_config import HiringConfig

    assert _start_hire_kpi_review_loop(SimpleNamespace(hiring=HiringConfig())) is None


def test_hire_kpi_review_loop_does_not_start_against_an_unconfigured_test_double():
    """A bare SimpleNamespace/MagicMock startup_config (most existing lifespan tests) must never start it."""
    from unittest.mock import MagicMock

    from app.gateway.app import _start_hire_kpi_review_loop

    assert _start_hire_kpi_review_loop(SimpleNamespace()) is None
    assert _start_hire_kpi_review_loop(MagicMock()) is None


@pytest.mark.asyncio
async def test_lifespan_registers_the_hire_kpi_review_loop_when_enabled():
    import asyncio as _asyncio
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock, MagicMock, patch

    from fastapi import FastAPI

    from app.gateway.app import lifespan
    from deerflow.config.hiring_config import HiringConfig

    @asynccontextmanager
    async def _noop_langgraph_runtime(_app, _startup_config):
        yield

    app = FastAPI()
    startup_config = SimpleNamespace(
        log_level="INFO",
        memory=SimpleNamespace(enabled=False, shutdown_flush_timeout_seconds=5.0),
        hiring=HiringConfig(kpi_check_enabled=True, kpi_check_interval_seconds=3600),
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
            task = app.state.hire_kpi_review_loop_task
            assert task is not None
            assert not task.done()

        assert task.done()
        assert task.cancelled()

    await _asyncio.sleep(0)
