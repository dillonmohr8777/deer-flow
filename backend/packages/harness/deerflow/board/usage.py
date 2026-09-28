"""Momo Board usage-ledger recording (Workspace Phase 4 item e7).

Every model call the board makes -- ``deerflow.board.triage.triage_board_thread``
and ``deerflow.board.concierge.generate_draft_body`` -- is written into the
existing operations-console usage ledger (``GET /api/console/usage-ledger``,
``app/gateway/routers/console.py``) as its own completed run plus a
``llm.ai.response``/``llm.error`` event, the same event shape
``deerflow.runtime.journal.RunJournal.on_llm_end``/``on_llm_error`` writes for
a normal agent run. Board calls happen outside any graph run, so there is no
``RunJournal`` attached to record through; this module writes the run/event
rows directly instead.

The ledger has no ``client_id`` column (only ``organization_id``, read from
``RunRow``), so the client is carried in the event's own metadata alongside
``board_thread_id`` for traceability.

Recording is best-effort and must never break triage or drafting: any
persistence failure (including a memory-backend deployment, which has no SQL
tables to write to) is logged and swallowed, matching
``triage_board_thread``/``generate_draft_body``'s own fail-safe stance that a
model call's outcome must never depend on a side write succeeding.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from deerflow.persistence.engine import get_session_factory
from deerflow.persistence.run.model import RunRow
from deerflow.runtime.events.catalog import LLM_AI_RESPONSE_EVENT, LLM_ERROR_EVENT
from deerflow.runtime.events.store.db import DbRunEventStore
from deerflow.runtime.user_context import get_effective_user_id

logger = logging.getLogger(__name__)


class RecordBoardUsage(Protocol):
    async def __call__(
        self,
        *,
        caller: str,
        attempt_status: str,
        organization_id: str | None = None,
        client_id: str | None = None,
        board_thread_id: str | None = None,
        requested_model: str | None = None,
        response: Any = None,
        error_type: str | None = None,
    ) -> None: ...


def _usage_and_resolved_model(response: Any) -> tuple[dict[str, Any], str | None]:
    """Extract token usage and the resolved model name from an LLM response.

    Mirrors ``RunJournal.on_llm_end``'s own extraction, which is the single
    other place this codebase reads these two attributes off an
    ``AIMessage``-shaped response.
    """
    usage = getattr(response, "usage_metadata", None)
    usage_dict = dict(usage) if usage else {}
    response_metadata = getattr(response, "response_metadata", None) or {}
    resolved_model = response_metadata.get("model_name") or response_metadata.get("model") if isinstance(response_metadata, dict) else None
    return usage_dict, resolved_model


async def record_board_model_usage(
    *,
    caller: str,
    attempt_status: str,
    organization_id: str | None = None,
    client_id: str | None = None,
    board_thread_id: str | None = None,
    requested_model: str | None = None,
    response: Any = None,
    error_type: str | None = None,
) -> None:
    """Record one board model call as a completed run in the usage ledger.

    ``caller`` becomes the synthetic run's ``assistant_id`` (``board_triage``
    or ``board_concierge``), matching ``ConsoleUsageLedgerItem.assistant_id``.
    """
    try:
        session_factory = get_session_factory()
        if session_factory is None:
            # Memory backend: no ledger tables exist to write to.
            return

        usage: dict[str, Any] = {}
        resolved_model: str | None = None
        if response is not None:
            usage, resolved_model = _usage_and_resolved_model(response)

        thread_id = f"board:{board_thread_id}" if board_thread_id else f"board:{caller}:{uuid.uuid4()}"
        run_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        status = "success" if attempt_status == "success" else "error"

        async with session_factory() as session:
            session.add(
                RunRow(
                    run_id=run_id,
                    thread_id=thread_id,
                    assistant_id=caller,
                    user_id=get_effective_user_id(),
                    organization_id=organization_id,
                    status=status,
                    operation_kind="run",
                    model_name=resolved_model or requested_model,
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.commit()

        event = LLM_AI_RESPONSE_EVENT if attempt_status == "success" else LLM_ERROR_EVENT
        store = DbRunEventStore(session_factory)
        await store.put(
            thread_id=thread_id,
            run_id=run_id,
            event_type=event.event_type,
            category=event.category,
            content="",
            metadata={
                "usage": usage,
                "provider_attempt_id": run_id,
                "attempt_status": attempt_status,
                "caller": caller,
                "requested_model": requested_model,
                "resolved_model": resolved_model,
                "error_type": error_type,
                "client_id": client_id,
                "board_thread_id": board_thread_id,
            },
        )
    except Exception:
        logger.warning("Failed to record board model usage (%s) into the usage ledger", caller, exc_info=True)


RecordBoardUsageFn = Callable[..., Awaitable[None]]
