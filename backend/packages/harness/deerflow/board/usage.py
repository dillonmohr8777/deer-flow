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

``GET /api/console/usage-ledger`` (and ``/api/console/stats``,
``/api/console/usage``) filter every query on the *querying user's own*
``RunRow.user_id`` (``app/gateway/routers/console.py::_owner_filters``) --
this endpoint is per-caller, not per-organization. Callers of this module
must therefore pass a real, resolvable ``user_id`` (e.g. the board thread's
creator); the ``get_effective_user_id()`` fallback only works inside a real
request context (an HTTP handler or similar), never from a background loop
with no such context, where it resolves to a synthetic default no real
account's ledger query can ever match.

That per-caller filter itself resolves through ``get_current_user()``
(``app/gateway/deps.py``), which returns ``request.state.storage_user_id``
when set -- a *shared* organization has its own dedicated storage principal
(``OrganizationRow.storage_user_id``), distinct from any individual member's
id, and every run made inside it (board or otherwise) is stamped with that
principal, not the acting person's id. Only a *private* organization uses
the actor's own id as its storage principal. So the ``user_id`` a caller
passes in here is only a starting point: this module resolves the thread's
actual organization to the org's real storage principal when it has one,
falling back to the passed-in id only for that person's own private org.

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
from deerflow.persistence.organizations.identity import private_organization_id
from deerflow.persistence.organizations.model import OrganizationRow
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
        user_id: str | None = None,
        requested_model: str | None = None,
        response: Any = None,
        error_type: str | None = None,
    ) -> None: ...


async def _resolve_ledger_user_id(session: Any, *, organization_id: str | None, fallback_user_id: str | None) -> str | None:
    """Return the ``RunRow.user_id`` that ``get_current_user()`` will actually filter on.

    A shared organization's dedicated ``storage_user_id`` wins whenever the
    org has one; ``fallback_user_id`` (typically the board thread's creator)
    is only correct when that person's own private organization is the one
    in play. See the module docstring for why.
    """
    if organization_id:
        organization = await session.get(OrganizationRow, organization_id)
        if organization is not None and organization.storage_user_id:
            return organization.storage_user_id
        if fallback_user_id and organization_id == private_organization_id(fallback_user_id):
            return fallback_user_id
    return fallback_user_id


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
    user_id: str | None = None,
    requested_model: str | None = None,
    response: Any = None,
    error_type: str | None = None,
) -> None:
    """Record one board model call as a completed run in the usage ledger.

    ``caller`` becomes the synthetic run's ``assistant_id`` (``board_triage``
    or ``board_concierge``), matching ``ConsoleUsageLedgerItem.assistant_id``.
    ``user_id`` is a starting point for the real owner to stamp the run with
    (see the module docstring): when ``organization_id`` names a shared
    organization with its own storage principal, that principal wins over
    ``user_id``; ``user_id`` (falling back to ``get_effective_user_id()`` for
    callers made from a real request context) is used as-is only for a
    private organization.
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
        fallback_user_id = user_id or get_effective_user_id()

        input_tokens = int(usage.get("input_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or 0)
        total_tokens = int(usage.get("total_tokens") or 0) or (input_tokens + output_tokens)
        usage_model_key = resolved_model or requested_model
        token_usage_by_model = {usage_model_key: usage} if usage_model_key and usage else {}

        # The RunRow and the event are two separate transactions (DbRunEventStore.put()
        # manages its own session/locking for seq assignment, so there is no cheap way
        # to share one transaction without duplicating that locking here). Write the
        # event first: an event with no matching RunRow is invisible everywhere (the
        # ledger's inner join excludes it, and /console/stats/usage read RunRow alone),
        # while the reverse order risks an orphaned RunRow whose token totals would
        # still count in that user's aggregate stats with no ledger line to explain them.
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

        async with session_factory() as session:
            resolved_user_id = await _resolve_ledger_user_id(session, organization_id=organization_id, fallback_user_id=fallback_user_id)
            session.add(
                RunRow(
                    run_id=run_id,
                    thread_id=thread_id,
                    assistant_id=caller,
                    user_id=resolved_user_id,
                    organization_id=organization_id,
                    status=status,
                    operation_kind="run",
                    model_name=resolved_model or requested_model,
                    total_input_tokens=input_tokens,
                    total_output_tokens=output_tokens,
                    total_tokens=total_tokens,
                    llm_call_count=1 if attempt_status == "success" else 0,
                    token_usage_by_model=token_usage_by_model,
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.commit()
    except Exception:
        logger.warning("Failed to record board model usage (%s) into the usage ledger", caller, exc_info=True)


RecordBoardUsageFn = Callable[..., Awaitable[None]]
