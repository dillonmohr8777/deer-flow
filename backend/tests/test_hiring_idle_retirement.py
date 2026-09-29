"""Tests for idle-probation auto-retirement of Momentum agent hires (queue item e12).

EXECUTIVE.md Hiring rule: "A hire idle 7 days ... is retired automatically."
Covers the accept bar directly: an idle hire with no attributable run
activity for the configured window is retired and the retirement is
announced to ``#exec``; an active hire, a freshly created hire still inside
its grace period, an already-retired hire, and a hire with active reports of
its own are all left untouched. The KPI half of the probation rule is
covered separately in ``tests/test_hiring_kpi_review.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from org_isolation_fixtures import ORG_A, ORG_B, USER_A, acting_as, org_world  # noqa: F401

from deerflow.hiring.retirement import evaluate_all_hire_idle_retirements, evaluate_hire_idle_retirement
from deerflow.persistence.hiring.model import HiredAgentRow, HireStatus
from deerflow.persistence.hiring.sql import HiredAgentRepository
from deerflow.persistence.run.model import RunRow
from deerflow.persistence.team_board import TeamBoardRepository
from deerflow.tools.exec_seat_tools import announce_to_exec


async def _seed_hire(
    session_factory,
    *,
    organization_id: str,
    agent_name: str,
    manager_agent_name: str = "ceo-agent",
    created_at: datetime,
    status: str = HireStatus.ACTIVE,
) -> dict:
    """Insert a hire row directly, with a controllable ``created_at`` (idle-clock baseline)."""
    row = HiredAgentRow(
        id=f"hire-{agent_name}",
        organization_id=organization_id,
        agent_name=agent_name,
        title="Report",
        manager_agent_name=manager_agent_name,
        depth=2,
        status=status,
        created_at=created_at,
        updated_at=created_at,
    )
    async with session_factory() as session, session.begin():
        session.add(row)
    return row.to_dict()


async def _run(session_factory, *, organization_id: str, agent_name: str, created_at: datetime) -> None:
    async with session_factory() as session, session.begin():
        session.add(
            RunRow(
                run_id=f"run-{agent_name}-{created_at.timestamp()}",
                thread_id=f"thread-{agent_name}",
                assistant_id=agent_name,
                organization_id=organization_id,
                status="success",
                created_at=created_at,
                updated_at=created_at,
            )
        )


async def _run_stamped_only_by_metadata(session_factory, *, organization_id: str, agent_name: str, created_at: datetime) -> None:
    """A run whose raw assistant_id is the default lead agent, naming *agent_name*
    only through the effective_agent_name metadata stamp (queue item f95's shape:
    a run that only ever named its agent through context.agent_name)."""
    from deerflow.persistence.exec_seats import EFFECTIVE_AGENT_NAME_METADATA_KEY

    async with session_factory() as session, session.begin():
        session.add(
            RunRow(
                run_id=f"run-meta-{agent_name}-{created_at.timestamp()}",
                thread_id=f"thread-meta-{agent_name}",
                assistant_id="lead_agent",
                organization_id=organization_id,
                status="success",
                created_at=created_at,
                updated_at=created_at,
                metadata_json={EFFECTIVE_AGENT_NAME_METADATA_KEY: agent_name},
            )
        )


@pytest.mark.asyncio
async def test_idle_hire_is_retired_and_announced(org_world):  # noqa: F811
    repo = HiredAgentRepository(org_world)
    team_repo = TeamBoardRepository(org_world)
    now = datetime.now(UTC)
    with acting_as(USER_A, ORG_A):
        await team_repo.ensure_default_channels(created_by_user_id=USER_A)
        hire = await _seed_hire(org_world, organization_id=ORG_A, agent_name="cmo-report", created_at=now - timedelta(days=10))

        updated = await evaluate_hire_idle_retirement(repo, hire, now=now, announce=announce_to_exec)

        assert updated["status"] == HireStatus.RETIRED
        assert updated["retired_at"] is not None

        exec_channel = next(c for c in await team_repo.list_channels() if c["slug"] == "exec")
        messages = await team_repo.list_messages(exec_channel["id"])
    assert any("cmo-report" in m["body"] and "idle" in m["body"] for m in messages)


@pytest.mark.asyncio
async def test_hire_with_recent_run_activity_is_not_retired(org_world):  # noqa: F811
    repo = HiredAgentRepository(org_world)
    now = datetime.now(UTC)
    with acting_as(USER_A, ORG_A):
        hire = await _seed_hire(org_world, organization_id=ORG_A, agent_name="cmo-report", created_at=now - timedelta(days=30))
        await _run(org_world, organization_id=ORG_A, agent_name="cmo-report", created_at=now - timedelta(days=2))

        updated = await evaluate_hire_idle_retirement(repo, hire, now=now)

    assert updated["status"] == HireStatus.ACTIVE


@pytest.mark.asyncio
async def test_a_run_named_only_through_the_metadata_stamp_still_counts_as_activity(org_world):  # noqa: F811
    """f118(d): last_activity_at must match the effective_agent_name metadata
    stamp, not only a raw assistant_id -- otherwise a hire whose runs always
    go through the default lead agent (naming itself only via
    context.agent_name) reads as permanently idle."""
    repo = HiredAgentRepository(org_world)
    now = datetime.now(UTC)
    with acting_as(USER_A, ORG_A):
        hire = await _seed_hire(org_world, organization_id=ORG_A, agent_name="cmo-report", created_at=now - timedelta(days=30))
        await _run_stamped_only_by_metadata(org_world, organization_id=ORG_A, agent_name="cmo-report", created_at=now - timedelta(days=1))

        updated = await evaluate_hire_idle_retirement(repo, hire, now=now)

    assert updated["status"] == HireStatus.ACTIVE


@pytest.mark.asyncio
async def test_freshly_hired_report_with_no_runs_yet_gets_a_grace_period(org_world):  # noqa: F811
    """A hire created 3 days ago with no runs at all must not be retired before its
    own creation date gives it 7 days -- the idle clock starts at created_at,
    not at "no run has ever happened"."""
    repo = HiredAgentRepository(org_world)
    now = datetime.now(UTC)
    with acting_as(USER_A, ORG_A):
        hire = await _seed_hire(org_world, organization_id=ORG_A, agent_name="cmo-report", created_at=now - timedelta(days=3))

        updated = await evaluate_hire_idle_retirement(repo, hire, now=now)

    assert updated["status"] == HireStatus.ACTIVE


@pytest.mark.asyncio
async def test_a_name_reused_from_old_run_activity_does_not_backdate_a_fresh_hire(org_world):  # noqa: F811
    """review finding (high, reproduced): last_activity_at matches by name
    with no floor at the hire's own creation, so an old run under the same
    name (a previous, now-retired hire that held it, or the identity's own
    pre-hire history) could make a brand-new hire look idle on its very
    first sweep. The idle clock must never start before this hire's own
    created_at."""
    repo = HiredAgentRepository(org_world)
    now = datetime.now(UTC)
    with acting_as(USER_A, ORG_A):
        await _run(org_world, organization_id=ORG_A, agent_name="cmo-report", created_at=now - timedelta(days=20))
        hire = await _seed_hire(org_world, organization_id=ORG_A, agent_name="cmo-report", created_at=now - timedelta(hours=1))

        updated = await evaluate_hire_idle_retirement(repo, hire, now=now)

    assert updated["status"] == HireStatus.ACTIVE


@pytest.mark.asyncio
async def test_a_hire_with_active_reports_of_its_own_is_left_alone(org_world):  # noqa: F811
    """Mirrors assert_can_retire's own guard: retiring a manager must never orphan its reports."""
    repo = HiredAgentRepository(org_world)
    now = datetime.now(UTC)
    with acting_as(USER_A, ORG_A):
        manager = await _seed_hire(org_world, organization_id=ORG_A, agent_name="cmo-report", created_at=now - timedelta(days=30))
        await _seed_hire(org_world, organization_id=ORG_A, agent_name="cmo-sub-report", manager_agent_name="cmo-report", created_at=now - timedelta(days=1))

        updated = await evaluate_hire_idle_retirement(repo, manager, now=now)

    assert updated["status"] == HireStatus.ACTIVE


@pytest.mark.asyncio
async def test_an_already_retired_hire_is_left_alone(org_world):  # noqa: F811
    repo = HiredAgentRepository(org_world)
    now = datetime.now(UTC)
    with acting_as(USER_A, ORG_A):
        hire = await _seed_hire(org_world, organization_id=ORG_A, agent_name="cmo-report", created_at=now - timedelta(days=30), status=HireStatus.RETIRED)

        updated = await evaluate_hire_idle_retirement(repo, hire, now=now)

    assert updated is hire


@pytest.mark.asyncio
async def test_run_activity_in_another_org_never_counts_toward_this_orgs_hire(org_world):  # noqa: F811
    repo = HiredAgentRepository(org_world)
    now = datetime.now(UTC)
    with acting_as(USER_A, ORG_A):
        hire = await _seed_hire(org_world, organization_id=ORG_A, agent_name="cmo-report", created_at=now - timedelta(days=10))

    await _run(org_world, organization_id=ORG_B, agent_name="cmo-report", created_at=now - timedelta(hours=1))

    with acting_as(USER_A, ORG_A):
        updated = await evaluate_hire_idle_retirement(repo, hire, now=now)

    assert updated["status"] == HireStatus.RETIRED


@pytest.mark.asyncio
async def test_evaluate_all_hire_idle_retirements_covers_every_active_hire(org_world):  # noqa: F811
    repo = HiredAgentRepository(org_world)
    now = datetime.now(UTC)
    with acting_as(USER_A, ORG_A):
        await _seed_hire(org_world, organization_id=ORG_A, agent_name="idle-report", created_at=now - timedelta(days=10))
        await _seed_hire(org_world, organization_id=ORG_A, agent_name="busy-report", created_at=now - timedelta(days=30))
        await _run(org_world, organization_id=ORG_A, agent_name="busy-report", created_at=now - timedelta(hours=1))

        results = await evaluate_all_hire_idle_retirements(repo, now=now)

    by_name = {r["agent_name"]: r for r in results}
    assert by_name["idle-report"]["status"] == HireStatus.RETIRED
    assert by_name["busy-report"]["status"] == HireStatus.ACTIVE


@pytest.mark.asyncio
async def test_custom_idle_days_threshold_is_respected(org_world):  # noqa: F811
    repo = HiredAgentRepository(org_world)
    now = datetime.now(UTC)
    with acting_as(USER_A, ORG_A):
        hire = await _seed_hire(org_world, organization_id=ORG_A, agent_name="cmo-report", created_at=now - timedelta(days=4))

        untouched = await evaluate_hire_idle_retirement(repo, hire, now=now, idle_days=7)
        assert untouched["status"] == HireStatus.ACTIVE

        retired = await evaluate_hire_idle_retirement(repo, hire, now=now, idle_days=3)
        assert retired["status"] == HireStatus.RETIRED


# ---------------------------------------------------------------------------
# Gateway lifespan registration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hire_idle_retirement_loop_starts_when_enabled():
    import asyncio

    from app.gateway.app import _start_hire_idle_retirement_loop
    from deerflow.config.hiring_config import HiringConfig

    startup_config = SimpleNamespace(hiring=HiringConfig(retirement_check_enabled=True, retirement_check_interval_seconds=60))
    task = _start_hire_idle_retirement_loop(startup_config)
    try:
        assert task is not None
        assert not task.done()
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_hire_idle_retirement_loop_does_not_start_by_default():
    from app.gateway.app import _start_hire_idle_retirement_loop
    from deerflow.config.hiring_config import HiringConfig

    assert _start_hire_idle_retirement_loop(SimpleNamespace(hiring=HiringConfig())) is None


def test_hire_idle_retirement_loop_does_not_start_against_an_unconfigured_test_double():
    """A bare SimpleNamespace/MagicMock startup_config (most existing lifespan tests) must never start it."""
    from unittest.mock import MagicMock

    from app.gateway.app import _start_hire_idle_retirement_loop

    assert _start_hire_idle_retirement_loop(SimpleNamespace()) is None
    assert _start_hire_idle_retirement_loop(MagicMock()) is None
