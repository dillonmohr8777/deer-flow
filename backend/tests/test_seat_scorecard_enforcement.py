"""Tests for scheduling the weekly agent-seat scorecard sweep (queue item e11).

``deerflow.exec_seats.scorecard.evaluate_all_seat_scorecards`` already knows
how to post/miss a seat's weekly scorecard (see ``test_agent_seat_scorecard.py``
for that accept bar); this file covers the scheduling half, mirroring
``test_seat_budget_enforcement.py``'s loop-wiring tests: the Gateway lifespan
registers a recurring sweep when configured, and never does by default or
against an unconfigured test double.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from org_isolation_fixtures import ORG_A, ORG_B, USER_A, USER_B, acting_as, org_world  # noqa: F401


async def _succeed(_seat: dict) -> str:
    return "Steady week, on KPI."


@pytest.mark.asyncio
async def test_sweep_evaluates_each_organizations_seats_in_its_own_context(org_world):  # noqa: F811
    """Review finding (low, test gap): _run_seat_scorecard_sweep's per-org storage-context
    switch (mirroring f95's budget sweep) was untested -- a seat's scorecard must land only
    in its own organization's #exec, never a sibling org's."""
    from app.gateway.app import _run_seat_scorecard_sweep
    from deerflow.persistence.exec_seats import AgentSeatRepository, AgentSeatStatus
    from deerflow.persistence.team_board import TeamBoardRepository

    repo = AgentSeatRepository(org_world)
    team_repo = TeamBoardRepository(org_world)

    # Distinct titles (not just agent names) so each org's post is identifiable by body text.
    with acting_as(USER_A, ORG_A):
        await team_repo.ensure_default_channels(created_by_user_id=USER_A)
        seat_a = await repo.claim_seat(seat="CMO", agent_name="cmo-agent-a", weekly_token_budget=0, claimed_by_user_id=USER_A)
        await repo.patch_seat(seat_a["id"], status=AgentSeatStatus.RATIFIED, ratified_by_user_id=USER_A)
    with acting_as(USER_B, ORG_B):
        await team_repo.ensure_default_channels(created_by_user_id=USER_B)
        seat_b = await repo.claim_seat(seat="CTO", agent_name="cto-agent-b", weekly_token_budget=0, claimed_by_user_id=USER_B)
        await repo.patch_seat(seat_b["id"], status=AgentSeatStatus.RATIFIED, ratified_by_user_id=USER_B)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("deerflow.exec_seats.scorecard.generate_scorecard_body", _succeed)
        await _run_seat_scorecard_sweep()

    with acting_as(USER_A, ORG_A):
        exec_a = next(c for c in await team_repo.list_channels() if c["slug"] == "exec")
        messages_a = await team_repo.list_messages(exec_a["id"])
        updated_a = await repo.get_seat(seat_a["id"])
    with acting_as(USER_B, ORG_B):
        exec_b = next(c for c in await team_repo.list_channels() if c["slug"] == "exec")
        messages_b = await team_repo.list_messages(exec_b["id"])
        updated_b = await repo.get_seat(seat_b["id"])

    assert updated_a["missed_scorecards"] == 0
    assert updated_b["missed_scorecards"] == 0
    assert any("[CMO]" in m["body"] for m in messages_a)
    assert not any("[CTO]" in m["body"] for m in messages_a)
    assert any("[CTO]" in m["body"] for m in messages_b)
    assert not any("[CMO]" in m["body"] for m in messages_b)


@pytest.mark.asyncio
async def test_seat_scorecard_loop_starts_when_enabled():
    import asyncio

    from app.gateway.app import _start_seat_scorecard_loop
    from deerflow.config.exec_seats_config import ExecSeatsConfig

    startup_config = SimpleNamespace(exec_seats=ExecSeatsConfig(scorecard_check_enabled=True, scorecard_check_interval_seconds=60))
    task = _start_seat_scorecard_loop(startup_config)
    try:
        assert task is not None
        assert not task.done()
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_seat_scorecard_loop_does_not_start_by_default():
    from app.gateway.app import _start_seat_scorecard_loop
    from deerflow.config.exec_seats_config import ExecSeatsConfig

    assert _start_seat_scorecard_loop(SimpleNamespace(exec_seats=ExecSeatsConfig())) is None


def test_seat_scorecard_loop_does_not_start_against_an_unconfigured_test_double():
    """A bare SimpleNamespace/MagicMock startup_config (most existing lifespan tests) must never start it."""
    from unittest.mock import MagicMock

    from app.gateway.app import _start_seat_scorecard_loop

    assert _start_seat_scorecard_loop(SimpleNamespace()) is None
    assert _start_seat_scorecard_loop(MagicMock()) is None


@pytest.mark.asyncio
async def test_lifespan_registers_the_seat_scorecard_loop_when_enabled():
    import asyncio as _asyncio
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock, MagicMock, patch

    from fastapi import FastAPI

    from app.gateway.app import lifespan
    from deerflow.config.exec_seats_config import ExecSeatsConfig

    @asynccontextmanager
    async def _noop_langgraph_runtime(_app, _startup_config):
        yield

    app = FastAPI()
    startup_config = SimpleNamespace(
        log_level="INFO",
        memory=SimpleNamespace(enabled=False, shutdown_flush_timeout_seconds=5.0),
        exec_seats=ExecSeatsConfig(scorecard_check_enabled=True, scorecard_check_interval_seconds=3600),
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
            task = app.state.seat_scorecard_loop_task
            assert task is not None
            assert not task.done()

        assert task.done()
        assert task.cancelled()

    await _asyncio.sleep(0)
