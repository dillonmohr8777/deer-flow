"""Tests for the weekly KPI-review sweep of Momentum agent hires (queue item
e12, agent-hiring) -- the KPI half of EXECUTIVE.md's Probation rule
("missing its KPI 2 weeks running is retired automatically"). The idle half
is covered separately in ``tests/test_hiring_idle_retirement.py``.

Covers the accept bar with a stubbed model (``generate``): a "met" verdict
resets the miss counter, a "missed"/unreadable one counts as a miss, and the
second consecutive miss retires the hire -- unless it still has active
reports of its own.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from org_isolation_fixtures import ORG_A, USER_A, acting_as, org_world  # noqa: F401

from deerflow.hiring.kpi_review import evaluate_all_hire_kpi_reviews, evaluate_hire_kpi
from deerflow.persistence.hiring.model import HireStatus
from deerflow.persistence.hiring.sql import HiredAgentRepository
from deerflow.persistence.team_board import TeamBoardRepository
from deerflow.tools.exec_seat_tools import announce_to_exec


async def _seed_hire(repo: HiredAgentRepository, *, agent_name: str, manager_agent_name: str = "ceo-agent") -> dict:
    return await repo.create_hire(agent_name=agent_name, title="Report", manager_agent_name=manager_agent_name, depth=2, kpi="ship weekly")


async def _met(_hire: dict) -> bool:
    return True


async def _missed(_hire: dict) -> bool:
    return False


async def _unreadable(_hire: dict) -> bool | None:
    return None


@pytest.mark.asyncio
async def test_met_kpi_resets_misses_and_announces(org_world):  # noqa: F811
    repo = HiredAgentRepository(org_world)
    team_repo = TeamBoardRepository(org_world)
    now = datetime.now(UTC)
    with acting_as(USER_A, ORG_A):
        await team_repo.ensure_default_channels(created_by_user_id=USER_A)
        hire = await _seed_hire(repo, agent_name="cmo-report")
        hire = await repo.record_kpi_check_result(hire["id"], met=False, now=now - timedelta(days=8))  # one prior miss, now stale

        updated = await evaluate_hire_kpi(repo, hire, now=now, announce=announce_to_exec, generate=_met)

        exec_channel = next(c for c in await team_repo.list_channels() if c["slug"] == "exec")
        messages = await team_repo.list_messages(exec_channel["id"])
    assert updated["missed_kpi_checks"] == 0
    assert updated["status"] == HireStatus.ACTIVE
    assert updated["last_kpi_check_at"] is not None
    assert any("cmo-report" in m["body"] and "met KPI" in m["body"] for m in messages)


@pytest.mark.asyncio
async def test_first_miss_is_recorded_and_does_not_retire(org_world):  # noqa: F811
    repo = HiredAgentRepository(org_world)
    team_repo = TeamBoardRepository(org_world)
    now = datetime.now(UTC)
    with acting_as(USER_A, ORG_A):
        await team_repo.ensure_default_channels(created_by_user_id=USER_A)
        hire = await _seed_hire(repo, agent_name="cmo-report")

        updated = await evaluate_hire_kpi(repo, hire, now=now, announce=announce_to_exec, generate=_missed)

        exec_channel = next(c for c in await team_repo.list_channels() if c["slug"] == "exec")
        messages = await team_repo.list_messages(exec_channel["id"])
    assert updated["missed_kpi_checks"] == 1
    assert updated["status"] == HireStatus.ACTIVE
    assert any("missed KPI" in m["body"] and "1/2" in m["body"] for m in messages)


@pytest.mark.asyncio
async def test_an_unreadable_verdict_counts_as_a_miss(org_world):  # noqa: F811
    repo = HiredAgentRepository(org_world)
    now = datetime.now(UTC)
    with acting_as(USER_A, ORG_A):
        hire = await _seed_hire(repo, agent_name="cmo-report")

        updated = await evaluate_hire_kpi(repo, hire, now=now, generate=_unreadable)

    assert updated["missed_kpi_checks"] == 1


@pytest.mark.asyncio
async def test_second_consecutive_miss_retires_the_hire(org_world):  # noqa: F811
    repo = HiredAgentRepository(org_world)
    team_repo = TeamBoardRepository(org_world)
    now = datetime.now(UTC)
    with acting_as(USER_A, ORG_A):
        await team_repo.ensure_default_channels(created_by_user_id=USER_A)
        hire = await _seed_hire(repo, agent_name="cmo-report")

        first_miss = now - timedelta(days=8)
        second_miss = now
        hire = await evaluate_hire_kpi(repo, hire, now=first_miss, generate=_missed)
        assert hire["missed_kpi_checks"] == 1
        assert hire["status"] == HireStatus.ACTIVE

        retired = await evaluate_hire_kpi(repo, hire, now=second_miss, announce=announce_to_exec, generate=_missed)

        exec_channel = next(c for c in await team_repo.list_channels() if c["slug"] == "exec")
        messages = await team_repo.list_messages(exec_channel["id"])
    assert retired["status"] == HireStatus.RETIRED
    assert retired["retired_at"] is not None
    assert any("retired" in m["body"] and "missed KPI two weeks running" in m["body"] for m in messages)


@pytest.mark.asyncio
async def test_a_met_kpi_after_one_miss_resets_the_counter_instead_of_retiring(org_world):  # noqa: F811
    repo = HiredAgentRepository(org_world)
    now = datetime.now(UTC)
    with acting_as(USER_A, ORG_A):
        hire = await _seed_hire(repo, agent_name="cmo-report")

        hire = await evaluate_hire_kpi(repo, hire, now=now - timedelta(days=8), generate=_missed)
        assert hire["missed_kpi_checks"] == 1

        recovered = await evaluate_hire_kpi(repo, hire, now=now, generate=_met)

    assert recovered["missed_kpi_checks"] == 0
    assert recovered["status"] == HireStatus.ACTIVE


@pytest.mark.asyncio
async def test_a_manager_with_active_reports_is_not_retired_on_its_second_miss(org_world):  # noqa: F811
    """Mirrors evaluate_hire_idle_retirement's own guard: retiring a manager must never orphan its reports."""
    repo = HiredAgentRepository(org_world)
    now = datetime.now(UTC)
    with acting_as(USER_A, ORG_A):
        manager = await _seed_hire(repo, agent_name="cmo-report")
        await _seed_hire(repo, agent_name="cmo-sub-report", manager_agent_name="cmo-report")

        manager = await evaluate_hire_kpi(repo, manager, now=now - timedelta(days=8), generate=_missed)
        assert manager["missed_kpi_checks"] == 1

        updated = await evaluate_hire_kpi(repo, manager, now=now, generate=_missed)

    assert updated["missed_kpi_checks"] == 2
    assert updated["status"] == HireStatus.ACTIVE


@pytest.mark.asyncio
async def test_a_hire_already_checked_this_week_is_not_re_evaluated(org_world):  # noqa: F811
    repo = HiredAgentRepository(org_world)
    now = datetime.now(UTC)
    calls: list[dict] = []

    async def _tracked(hire: dict) -> bool:
        calls.append(hire)
        return True

    with acting_as(USER_A, ORG_A):
        hire = await _seed_hire(repo, agent_name="cmo-report")
        hire = await repo.record_kpi_check_result(hire["id"], met=True, now=now - timedelta(days=2))

        untouched = await evaluate_hire_kpi(repo, hire, now=now, generate=_tracked)

    assert calls == []
    assert untouched is hire


@pytest.mark.asyncio
async def test_a_retired_hire_is_left_alone(org_world):  # noqa: F811
    repo = HiredAgentRepository(org_world)
    now = datetime.now(UTC)
    calls: list[dict] = []

    async def _tracked(hire: dict) -> bool:
        calls.append(hire)
        return True

    with acting_as(USER_A, ORG_A):
        hire = await _seed_hire(repo, agent_name="cmo-report")
        hire = await repo.retire(hire["id"])

        untouched = await evaluate_hire_kpi(repo, hire, now=now, generate=_tracked)

    assert calls == []
    assert untouched is hire


@pytest.mark.asyncio
async def test_evaluate_all_hire_kpi_reviews_covers_every_active_hire(org_world):  # noqa: F811
    repo = HiredAgentRepository(org_world)
    now = datetime.now(UTC)
    with acting_as(USER_A, ORG_A):
        await _seed_hire(repo, agent_name="steady-report")
        await _seed_hire(repo, agent_name="shaky-report")

        results = await evaluate_all_hire_kpi_reviews(repo, now=now, generate=_met)

    by_name = {r["agent_name"]: r for r in results}
    assert by_name["steady-report"]["missed_kpi_checks"] == 0
    assert by_name["shaky-report"]["missed_kpi_checks"] == 0
