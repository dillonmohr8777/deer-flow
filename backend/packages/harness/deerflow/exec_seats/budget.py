"""Weekly token-budget enforcement for Momentum agent seats (queue item e10).

Every ratified or claimed seat carries a ``weekly_token_budget``. This module
sums the seat's holder's actual token burn over the trailing week from the
usage ledger (the ``runs`` table, keyed by ``RunRow.assistant_id`` == the
seat's ``agent_name``) and pauses the seat when it crosses that budget,
announcing the block to ``#exec`` the same way a claim/ratify/reopen already
does (``deerflow.tools.exec_seat_tools``'s ``_announce``). A seat whose burn
has fallen back under budget (a new week, or work slowing down) is resumed
the same way -- "rebalance" is just re-running the check.

A budget of ``0`` means unlimited (no seat is paused for it), matching
``AgentSeatRepository.claim_seat``'s default.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from deerflow.persistence.exec_seats.model import AgentSeatStatus
from deerflow.persistence.exec_seats.sql import AgentSeatRepository

Announce = Callable[[str], Awaitable[None]]

_WEEK = timedelta(days=7)
_ACTIVE_STATUSES = frozenset({AgentSeatStatus.CLAIMED, AgentSeatStatus.RATIFIED})


def is_over_budget(burn: int, weekly_token_budget: int) -> bool:
    """Whether *burn* tokens this week exceeds *weekly_token_budget* (0 = unlimited)."""
    return weekly_token_budget > 0 and burn >= weekly_token_budget


async def evaluate_seat_budget(repo: AgentSeatRepository, seat: dict[str, Any], *, now: datetime | None = None, announce: Announce | None = None) -> dict[str, Any]:
    """Pause or resume one *seat* based on its trailing-week token burn.

    Returns the seat dict, updated if a pause/resume happened. A seat not
    currently claimed or ratified (e.g. reopened, nobody holds it) is left
    alone -- nothing is running under its name to pause.
    """
    if seat["status"] not in _ACTIVE_STATUSES:
        return seat
    now = now or datetime.now(UTC)
    burn = await repo.token_burn_since(organization_id=seat["organization_id"], agent_name=seat["agent_name"], since=now - _WEEK)
    over_budget = is_over_budget(burn, seat["weekly_token_budget"])
    already_paused = seat.get("paused_at") is not None
    if over_budget == already_paused:
        return seat
    updated = await repo.set_paused(seat["id"], paused=over_budget, now=now)
    if updated is None:
        return seat
    if announce is not None:
        if over_budget:
            await announce(f"blocked: seat {seat['seat']!r} paused, over its weekly budget ({burn}/{seat['weekly_token_budget']} tokens)")
        else:
            await announce(f"seat {seat['seat']!r} resumed, back under its weekly budget ({burn}/{seat['weekly_token_budget']} tokens)")
    return updated


async def evaluate_all_seat_budgets(repo: AgentSeatRepository, *, now: datetime | None = None, announce: Announce | None = None) -> list[dict[str, Any]]:
    """Run :func:`evaluate_seat_budget` over every seat in the active organization."""
    now = now or datetime.now(UTC)
    return [await evaluate_seat_budget(repo, seat, now=now, announce=announce) for seat in await repo.list_seats()]
