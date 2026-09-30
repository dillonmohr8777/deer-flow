"""Daily CEO Desk digest (queue item e14): "what shipped, what's stuck, what
needs my yes" in three lines.

Gathering the window (:func:`build_digest_window`) is pure counting over
``BoardRepository``/``AgentSeatRepository`` -- no model call, so it's cheap to
run on every scheduled tick regardless of whether a digest is actually due.
Drafting the digest text (:func:`generate_daily_digest`) mirrors
``deerflow.exec_seats.scorecard.generate_scorecard_body``'s single
best-effort ``create_chat_model`` + ``ainvoke`` call: the model may only
describe the grounded counts it's handed, never invent shipped work, stuck
items or approvals beyond them, and a model/configuration failure returns
``None`` rather than a silently empty or fabricated digest.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from deerflow.config import get_app_config
from deerflow.config.app_config import AppConfig
from deerflow.models import create_chat_model
from deerflow.persistence.board.model import BoardThreadStatus
from deerflow.persistence.board.sql import BoardRepository
from deerflow.persistence.exec_seats.model import AgentSeatStatus
from deerflow.persistence.exec_seats.sql import AgentSeatRepository
from deerflow.utils.llm_text import extract_response_text

logger = logging.getLogger(__name__)

_WINDOW = timedelta(hours=24)
_SHIPPED_STATUSES = frozenset({BoardThreadStatus.REPLIED, BoardThreadStatus.CLOSED})
_MAX_NAMED_SUBJECTS = 5


@dataclass(frozen=True)
class DigestWindow:
    """Grounded counts for one digest; the model may only describe these."""

    shipped_count: int
    shipped_subjects: list[str]
    stuck_count: int
    stuck_subjects: list[str]
    needs_my_yes_drafts: int
    needs_my_yes_ratifications: int


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    try:
        dt = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


async def build_digest_window(
    board_repo: BoardRepository,
    seat_repo: AgentSeatRepository,
    *,
    since: datetime | None = None,
    now: datetime | None = None,
) -> DigestWindow:
    """Count what shipped, what's stuck, and what still needs a yes.

    "Shipped" is a thread that reached ``replied``/``closed`` since *since*
    (default: the trailing 24h). "Stuck" is any thread not yet
    ``replied``/``closed`` whose last update predates *since* -- open, and
    already open before this window started. "Needs my yes" is the same
    live count the needs-my-yes queue itself shows (drafted threads plus
    claimed/unratified seats), not windowed, since it describes right now.
    """
    now = now or datetime.now(UTC)
    since = since or now - _WINDOW

    threads = await board_repo.list_threads()
    shipped = [t for t in threads if t.get("status") in _SHIPPED_STATUSES and (updated_at := _parse_dt(t.get("updated_at"))) is not None and updated_at >= since]
    stuck = [t for t in threads if t.get("status") not in _SHIPPED_STATUSES and (updated_at := _parse_dt(t.get("updated_at"))) is not None and updated_at < since]
    drafts = await board_repo.list_threads(status=BoardThreadStatus.DRAFTED)
    claims = await seat_repo.list_seats(status=AgentSeatStatus.CLAIMED)

    return DigestWindow(
        shipped_count=len(shipped),
        shipped_subjects=[t.get("subject", "") for t in shipped],
        stuck_count=len(stuck),
        stuck_subjects=[t.get("subject", "") for t in stuck],
        needs_my_yes_drafts=len(drafts),
        needs_my_yes_ratifications=len(claims),
    )


def _named(subjects: list[str]) -> str:
    named = [s for s in subjects[:_MAX_NAMED_SUBJECTS] if s]
    return f" ({', '.join(named)})" if named else ""


def _prompt(window: DigestWindow) -> str:
    reply_word = "reply" if window.needs_my_yes_drafts == 1 else "replies"
    return (
        "You write a 3-line daily digest for Momentum's owner: one line each for what shipped, "
        "what's stuck, and what needs your yes. No preamble, no greeting, no sign-off.\n"
        "Use only the grounded facts below -- do not invent names, numbers or events beyond them. "
        "If a count is zero, say so plainly rather than skipping the line or padding it out.\n\n"
        f"Shipped in the last day: {window.shipped_count} board thread(s) closed out{_named(window.shipped_subjects)}.\n"
        f"Stuck (open, untouched since before the window): {window.stuck_count} board thread(s){_named(window.stuck_subjects)}.\n"
        f"Needs your yes right now: {window.needs_my_yes_drafts} drafted board {reply_word} awaiting approval, "
        f"{window.needs_my_yes_ratifications} seat claim(s) awaiting ratification."
    )


async def generate_daily_digest(
    window: DigestWindow,
    *,
    app_config: AppConfig | None = None,
    model_name: str | None = None,
    attach_tracing: bool = True,
) -> str | None:
    """Draft the digest text for *window* via a single best-effort model call.

    Returns ``None`` on model/configuration failure or invalid content, so a
    broken digest never silently reports "nothing happened".
    """
    try:
        config = app_config or get_app_config()
        model = create_chat_model(name=model_name, thinking_enabled=False, app_config=config, attach_tracing=attach_tracing)
        response = await model.ainvoke([{"role": "user", "content": _prompt(window)}], config={"run_name": "ceo_desk_digest"})
        content = getattr(response, "content", None)
        if not isinstance(content, (str, list)):
            logger.warning("Digest model returned invalid content")
            return None
        return extract_response_text(content).strip()
    except Exception:
        logger.warning("Digest generation failed", exc_info=True)
        return None
