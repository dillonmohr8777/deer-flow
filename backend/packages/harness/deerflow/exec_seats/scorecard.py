"""Weekly scorecard enforcement for Momentum agent seats (queue item e11).

EXECUTIVE.md rule 3: "Every Friday, each employee posts a scorecard. Two
missed weeks and the title reopens." Only a *ratified* seat (a confirmed
title, not a still-contested claim) owes a weekly scorecard. Each seat is
conclusively evaluated at most once per trailing week (``AgentSeatRow.last_scorecard_at``),
so a shorter sweep interval only means a due seat is noticed sooner, never
evaluated twice for the same week.

Scorecard generation mirrors ``deerflow.board.triage``'s
``create_chat_model`` + ``ainvoke`` plumbing: a single best-effort model call
that returns ``None`` on infrastructure/model failure and a string on a
completed generation (including an empty response). Failures and unconfirmed
delivery are inconclusive: they preserve the employee's miss streak, title
and last evaluated week. A completed blank response is an evaluated miss
only after its miss notice reaches ``#exec``.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from deerflow.config import get_app_config
from deerflow.config.app_config import AppConfig
from deerflow.models import create_chat_model
from deerflow.persistence.exec_seats.model import AgentSeatStatus
from deerflow.persistence.exec_seats.sql import AgentSeatRepository
from deerflow.utils.llm_text import extract_response_text

logger = logging.getLogger(__name__)

# Unlike deerflow.exec_seats.budget's Announce (fire-and-forget, its
# pause/resume decision never depends on whether the post landed), this
# module's Announce reports whether the message actually reached #exec: a
# scorecard that was drafted but never delivered is not "posted" (see the
# success-requires-a-confirmed-post rule in evaluate_seat_scorecard below).
Announce = Callable[[str], Awaitable[bool]]
Generate = Callable[[dict[str, Any]], Awaitable[str | None]]

_WEEK = timedelta(days=7)
_MISSES_BEFORE_REOPEN = 2


async def generate_scorecard_body(
    seat: dict[str, Any],
    *,
    app_config: AppConfig | None = None,
    model_name: str | None = None,
    attach_tracing: bool = True,
) -> str | None:
    """Draft this week's scorecard for *seat* via a single best-effort model call.

    Returns ``None`` on model/configuration failure; a completed blank
    response returns ``""`` so infrastructure outages are not employee misses.
    *seat* may carry
    an optional ``weekly_token_burn`` key (this week's real usage, from
    ``AgentSeatRepository.token_burn_since``) -- the only grounded signal this
    module has about the seat holder's actual activity, so the prompt hands
    it over explicitly and tells the model not to invent specifics it has no
    way to know.
    """
    burn = seat.get("weekly_token_burn")
    budget = seat.get("weekly_token_budget") or 0
    usage_line = f"Usage this week: {burn} of {budget if budget else 'an unlimited'} weekly token budget.\n" if burn is not None else ""
    prompt = (
        f"You are {seat['agent_name']}, Momentum's {seat['seat']}.\n"
        f"Job scope: {seat.get('scope') or '(none recorded)'}\n"
        f"KPI: {seat.get('kpi') or '(none recorded)'}\n"
        f"{usage_line}"
        "Post this week's scorecard for the #exec channel: 2-3 plain sentences, no preamble. "
        "You have no record of specific tasks completed -- do not invent shipped work, numbers or events. "
        "Describe your activity level from the usage figure above (e.g. quiet, steady, heavy) and restate your KPI focus for next week."
    )
    try:
        config = app_config or get_app_config()
        model = create_chat_model(name=model_name, thinking_enabled=False, app_config=config, attach_tracing=attach_tracing)
        response = await model.ainvoke([{"role": "user", "content": prompt}], config={"run_name": "exec_seat_scorecard"})
        content = getattr(response, "content", None)
        if not isinstance(content, (str, list)):
            logger.warning("Scorecard model returned invalid content for seat %s", seat.get("seat"))
            return None
        text = extract_response_text(content).strip()
        return text
    except Exception:
        logger.warning("Scorecard generation failed for seat %s", seat.get("seat"), exc_info=True)
        return None


def _due(seat: dict[str, Any], now: datetime) -> bool:
    last = seat.get("last_scorecard_at")
    if last is None:
        return True
    if isinstance(last, str):
        last = datetime.fromisoformat(last)
    if last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    return last <= now - _WEEK


async def _confirmed_post(announce: Announce, text: str, seat: dict[str, Any]) -> bool:
    """Delivery failure is inconclusive, including adapters that unexpectedly raise."""
    try:
        posted = await announce(text)
    except Exception:
        logger.warning("Scorecard delivery failed for seat %s", seat.get("seat"), exc_info=True)
        return False
    if not posted:
        logger.warning("Scorecard delivery was not confirmed for seat %s", seat.get("seat"))
    return bool(posted)


async def evaluate_seat_scorecard(
    repo: AgentSeatRepository,
    seat: dict[str, Any],
    *,
    now: datetime | None = None,
    announce: Announce | None = None,
    generate: Generate | None = None,
) -> dict[str, Any]:
    """Run one weekly scorecard check for *seat*.

    Only a ratified seat is checked (a still-``claimed``/unratified title has
    no confirmed holder yet, and a ``reopened`` seat has nobody to post one).
    Not yet due this week (``last_scorecard_at`` within the trailing week)
    leaves the seat untouched. Success requires a *confirmed* scorecard post
    to ``#exec``. A completed blank generation counts as a miss only after a
    confirmed miss notice; the second consecutive evaluated miss reopens the
    seat (EXECUTIVE.md rule 3). The supplemental reopened notice is best-effort.

    Usage/model errors, ``generate`` returning ``None``, and absent/failed
    delivery are inconclusive. They neither increment nor reset the miss
    counter, change the title, nor advance ``last_scorecard_at``. The seat
    remains due for a later configured sweep. ``announce=None`` also skips
    generation, since this check cannot complete without a delivery route.
    """
    if seat["status"] != AgentSeatStatus.RATIFIED:
        return seat
    now = now or datetime.now(UTC)
    if not _due(seat, now):
        return seat
    if announce is None:
        logger.warning("Scorecard check has no delivery route for seat %s", seat.get("seat"))
        return seat
    generate = generate or generate_scorecard_body
    try:
        burn = await repo.token_burn_since(organization_id=seat["organization_id"], agent_name=seat["agent_name"], since=now - _WEEK)
        body = await generate({**seat, "weekly_token_burn": burn})
        if body is None:
            logger.warning("Scorecard generation was inconclusive for seat %s", seat.get("seat"))
            return seat
        body = body.strip()
    except Exception:
        logger.warning("Scorecard check was inconclusive for seat %s", seat.get("seat"), exc_info=True)
        return seat

    if body:
        if not await _confirmed_post(announce, f"[{seat['seat']}] weekly scorecard: {body}", seat):
            return seat
        updated = await repo.record_scorecard_result(seat["id"], success=True, now=now)
        return updated if updated is not None else seat

    misses = seat["missed_scorecards"] + 1
    if not await _confirmed_post(announce, f"[{seat['seat']}] missed this week's scorecard ({misses}/{_MISSES_BEFORE_REOPEN})", seat):
        return seat
    updated = await repo.record_scorecard_result(seat["id"], success=False, now=now)
    if updated is None:
        return seat
    if updated["missed_scorecards"] >= _MISSES_BEFORE_REOPEN:
        reopened = await repo.patch_seat(seat["id"], status=AgentSeatStatus.REOPENED)
        if reopened is None:
            return updated
        await _confirmed_post(announce, f"reopened {reopened['seat']} (held by {seat['agent_name']}): missed two weekly scorecards in a row", seat)
        return reopened
    return updated


async def evaluate_all_seat_scorecards(
    repo: AgentSeatRepository,
    *,
    now: datetime | None = None,
    announce: Announce | None = None,
    generate: Generate | None = None,
) -> list[dict[str, Any]]:
    """Run :func:`evaluate_seat_scorecard` over every seat in the active organization."""
    now = now or datetime.now(UTC)
    return [await evaluate_seat_scorecard(repo, seat, now=now, announce=announce, generate=generate) for seat in await repo.list_seats()]
