"""Weekly KPI review for Momentum agent hires -- the KPI half of EXECUTIVE.md's
Probation rule (queue item e12, hiring): "missing its KPI 2 weeks running is
retired automatically". The idle half lives in ``deerflow.hiring.retirement``.

Mirrors ``deerflow.exec_seats.scorecard`` almost exactly: a single
best-effort model call judges whether the hire met its KPI this week, a
failed/blank/ambiguous judgment counts as a miss just like a failed
scorecard generation does, and each hire is evaluated at most once per
trailing week (``HiredAgentRow.last_kpi_check_at``). Unlike a scorecard miss
(which reopens a seat), a second consecutive KPI miss retires the hire --
subject to the same "never orphan active reports" guard
``deerflow.hiring.retirement`` already applies, so a manager with active
reports of its own is left alone until they're retired first.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from deerflow.config import get_app_config
from deerflow.config.app_config import AppConfig
from deerflow.models import create_chat_model
from deerflow.persistence.hiring.model import HireStatus
from deerflow.persistence.hiring.sql import HiredAgentRepository
from deerflow.utils.llm_text import extract_response_text

logger = logging.getLogger(__name__)

Announce = Callable[[str], Awaitable[None]]
Generate = Callable[[dict[str, Any]], Awaitable[bool | None]]

_WEEK = timedelta(days=7)
_MISSES_BEFORE_RETIRE = 2


async def generate_kpi_verdict(
    hire: dict[str, Any],
    *,
    app_config: AppConfig | None = None,
    model_name: str | None = None,
    attach_tracing: bool = True,
) -> bool | None:
    """Judge whether *hire* met its KPI this week via a single best-effort model call.

    Returns ``True`` (met), ``False`` (missed), or ``None`` on any model
    failure or an answer that names neither -- a review this module can't
    read is treated the same as a missed one, mirroring
    ``exec_seats.scorecard.generate_scorecard_body``'s blank-counts-as-a-miss
    posture.
    """
    prompt = (
        f"You are the manager reviewing {hire['agent_name']}, Momentum's {hire.get('title') or 'report'}.\n"
        f"Job scope: {hire.get('job') or '(none recorded)'}\n"
        f"KPI: {hire.get('kpi') or '(none recorded)'}\n"
        "Did this report meet its KPI this week? Answer with a single word, MET or MISSED, "
        "then one plain sentence why."
    )
    try:
        config = app_config or get_app_config()
        model = create_chat_model(name=model_name, thinking_enabled=False, app_config=config, attach_tracing=attach_tracing)
        response = await model.ainvoke([{"role": "user", "content": prompt}], config={"run_name": "hire_kpi_review"})
        text = extract_response_text(getattr(response, "content", "")).strip()
        verdict = text.split()[0].strip(".:,").upper() if text else ""
        if verdict == "MET":
            return True
        if verdict == "MISSED":
            return False
        return None
    except Exception:
        logger.warning("KPI review failed for hire %s", hire.get("agent_name"), exc_info=True)
        return None


def _due(hire: dict[str, Any], now: datetime) -> bool:
    last = hire.get("last_kpi_check_at")
    if last is None:
        return True
    if isinstance(last, str):
        last = datetime.fromisoformat(last)
    if last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    return last <= now - _WEEK


async def evaluate_hire_kpi(
    repo: HiredAgentRepository,
    hire: dict[str, Any],
    *,
    now: datetime | None = None,
    announce: Announce | None = None,
    generate: Generate | None = None,
) -> dict[str, Any]:
    """Run one weekly KPI review for *hire*.

    Only an active hire is checked. Not yet due this week
    (``last_kpi_check_at`` within the trailing week) leaves it untouched. A
    "met" verdict resets the miss counter; a "missed" or unreadable one
    counts as a miss and, on the second consecutive miss, retires the hire
    -- unless it still has active reports of its own, in which case it's
    left alone (mirroring ``deerflow.hiring.retirement``'s own orphan guard)
    and becomes eligible once those reports are retired first.
    """
    if hire["status"] != HireStatus.ACTIVE:
        return hire
    now = now or datetime.now(UTC)
    if not _due(hire, now):
        return hire
    generate = generate or generate_kpi_verdict
    met = await generate(hire)

    updated = await repo.record_kpi_check_result(hire["id"], met=bool(met), now=now)
    if updated is None:
        return hire
    if met:
        if announce is not None:
            await announce(f"[{hire['agent_name']}] met KPI this week")
        return updated

    if announce is not None:
        await announce(f"[{hire['agent_name']}] missed KPI this week ({updated['missed_kpi_checks']}/{_MISSES_BEFORE_RETIRE})")
    if updated["missed_kpi_checks"] < _MISSES_BEFORE_RETIRE:
        return updated

    reports = await repo.list_reports_of(hire["agent_name"], status=HireStatus.ACTIVE)
    if reports:
        return updated

    retired = await repo.retire(updated["id"], now=now)
    if retired is None:
        return updated
    if announce is not None:
        await announce(f"retired {retired['agent_name']!r} ({retired.get('title') or 'report'}): missed KPI two weeks running")
    return retired


async def evaluate_all_hire_kpi_reviews(
    repo: HiredAgentRepository,
    *,
    now: datetime | None = None,
    announce: Announce | None = None,
    generate: Generate | None = None,
) -> list[dict[str, Any]]:
    """Run :func:`evaluate_hire_kpi` over every active hire in the active organization."""
    now = now or datetime.now(UTC)
    return [await evaluate_hire_kpi(repo, hire, now=now, announce=announce, generate=generate) for hire in await repo.list_hires()]
