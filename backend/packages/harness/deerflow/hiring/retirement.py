"""Idle-probation auto-retirement for Momentum agent hires (queue item e12, hiring).

EXECUTIVE.md's Hiring section, "Probation": "A hire idle 7 days, or missing
its KPI 2 weeks running, is retired automatically." This module closes the
idle half: a hire with no attributable run activity for
``idle_days_before_retirement`` days is retired the same way
``exec_seats.budget``/``exec_seats.scorecard`` pause or reopen a seat --
best-effort, announced to ``#exec``, never bypassing
``deerflow.hiring.workflow.assert_can_retire``'s own guards (in particular,
a hire with active reports of its own is left alone rather than orphaning
them; it becomes eligible once its reports are retired in a later sweep).

The KPI half ("missing its KPI 2 weeks running") lives separately in
``deerflow.hiring.kpi_review``, mirroring ``exec_seats.scorecard``'s
weekly-check mechanism.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from deerflow.persistence.hiring.model import HireStatus
from deerflow.persistence.hiring.sql import HiredAgentRepository

Announce = Callable[[str], Awaitable[None]]


def _coerce_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value


async def evaluate_hire_idle_retirement(
    repo: HiredAgentRepository,
    hire: dict[str, Any],
    *,
    now: datetime | None = None,
    idle_days: int = 7,
    announce: Announce | None = None,
) -> dict[str, Any]:
    """Retire *hire* if it has had no attributable run activity for *idle_days* days.

    Only an active hire is evaluated. The idle clock starts from the later of
    the hire's most recent run (``HiredAgentRepository.last_activity_at``) and
    its own ``created_at`` -- never earlier than *this* hire's creation, even
    when ``last_activity_at``'s name-based match picks up an older run from
    before this hire existed (a previous, now-retired hire that held the same
    name, or the identity's own pre-hire history). Without that floor, a
    freshly hired agent reusing an old or stale name could be retired on its
    very first sweep (review finding, high). A hire that still has active
    reports of its own is left untouched (``assert_can_retire`` would refuse
    it anyway); it becomes eligible on a later sweep once those reports are
    retired first.
    """
    if hire["status"] != HireStatus.ACTIVE:
        return hire
    now = now or datetime.now(UTC)
    last_active = _coerce_datetime(await repo.last_activity_at(organization_id=hire["organization_id"], agent_name=hire["agent_name"]))
    created = _coerce_datetime(hire["created_at"])
    baseline = max(last_active, created) if (last_active is not None and created is not None) else (last_active or created)
    if baseline is None or now - baseline < timedelta(days=idle_days):
        return hire

    reports = await repo.list_reports_of(hire["agent_name"], status=HireStatus.ACTIVE)
    if reports:
        # Mirrors assert_can_retire's own guard: retiring a manager must never
        # orphan its reports or free the budget still carved out for them.
        # Its reports become idle-eligible in their own right on a later sweep.
        return hire

    updated = await repo.retire(hire["id"], now=now)
    if updated is None:
        return hire
    if announce is not None:
        await announce(f"retired {hire['agent_name']!r} ({hire.get('title') or 'report'}): idle {idle_days}+ days")
    return updated


async def evaluate_all_hire_idle_retirements(
    repo: HiredAgentRepository,
    *,
    now: datetime | None = None,
    idle_days: int = 7,
    announce: Announce | None = None,
) -> list[dict[str, Any]]:
    """Run :func:`evaluate_hire_idle_retirement` over every active hire in the active organization."""
    now = now or datetime.now(UTC)
    return [await evaluate_hire_idle_retirement(repo, hire, now=now, idle_days=idle_days, announce=announce) for hire in await repo.list_hires()]
