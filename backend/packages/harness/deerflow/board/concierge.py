"""Momo Board draft concierge (Workspace Phase 4 item e5).

Behind ``config.board.concierge_enabled`` (default off), a background loop
drafts a reply for every ``new``/``triaged`` board thread and moves it to
``drafted``. This module never calls ``assert_can_approve``/``assert_can_reply``
and makes no write beyond one draft message plus the ``drafted`` status
transition -- an owner must still approve and send.

Unlike the human-triggered ``/threads/{id}/draft`` route
(``deerflow.board.workflow.assert_can_draft`` + two separate repository
calls, serialized by having exactly one human clicking one button), this is
a background loop with no such serialization: its own draft-generation call
can be slow enough for the thread to move on (approved, replied, or drafted
by someone else) before the write lands, and a multi-worker Gateway
deployment can run more than one pass concurrently. So the write itself is
``BoardRepository.try_add_momo_draft()``, a single compare-and-set
transaction (``UPDATE ... WHERE status IN ('new','triaged')`` gating the
draft-message insert) rather than the router's two-step
check-then-write -- a race never overwrites a status the thread already
moved past, and a losing race never leaves an orphaned draft message
behind. A per-thread failure (draft generation or the write) is logged and
skipped so it cannot abort the rest of the pass.

Draft generation mirrors ``deerflow.board.triage``'s LLM plumbing
(``create_chat_model`` + ``ainvoke``, no persistence dependency of its own)
and is injectable via ``generate_draft`` the same way tests stub
``triage_board_thread``'s model call.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Awaitable, Callable

from deerflow.config import get_app_config
from deerflow.config.app_config import AppConfig
from deerflow.models import create_chat_model
from deerflow.persistence.board.model import BoardThreadStatus
from deerflow.tracing import inject_langfuse_metadata
from deerflow.utils.llm_text import extract_response_text

logger = logging.getLogger(__name__)

_DRAFT_ELIGIBLE_STATUSES: tuple[str, ...] = (BoardThreadStatus.NEW, BoardThreadStatus.TRIAGED)

GenerateDraft = Callable[..., Awaitable[str | None]]


async def generate_draft_body(
    content: str,
    *,
    subject: str = "",
    kind: str = "",
    app_config: AppConfig | None = None,
    model_name: str | None = None,
    attach_tracing: bool = True,
) -> str | None:
    """Draft a reply body for one board thread's opening message.

    Returns ``None`` on any model failure or empty response so a caller
    leaves the thread untouched rather than drafting a broken reply --
    drafting is an aid, not a gate, matching ``triage_board_thread``'s own
    fail-safe stance.
    """
    rubric = (
        "You are Momo, an assistant drafting a reply on a client's board for a human owner to review, "
        "edit and approve before it is ever sent to the client. Write a short, warm, specific reply to "
        "the message below. Do not invent facts, prices, dates or commitments you cannot verify from the "
        "message itself; say the team will confirm anything you can't verify. Reply with the draft text "
        "only -- no preamble, no quotes, no signature block."
    )
    prompt = f"Kind: {kind or 'post'}\nSubject: {subject or '(none)'}\n\nMessage:\n-----\n{content}\n-----"

    try:
        config = app_config or get_app_config()
        model = create_chat_model(name=model_name, thinking_enabled=False, app_config=config, attach_tracing=attach_tracing)
        invoke_config: dict = {"run_name": "board_concierge_draft"}
        if attach_tracing:
            inject_langfuse_metadata(
                invoke_config,
                thread_id=None,
                user_id=None,
                assistant_id="board_concierge",
                model_name=model_name,
                environment=os.environ.get("DEER_FLOW_ENV") or os.environ.get("ENVIRONMENT"),
            )
        response = await model.ainvoke(
            [
                {"role": "system", "content": rubric},
                {"role": "user", "content": prompt},
            ],
            config=invoke_config,
        )
        draft = extract_response_text(getattr(response, "content", "")).strip()
        return draft or None
    except Exception:
        logger.warning("Board concierge draft generation failed; leaving thread undrafted", exc_info=True)
        return None


_BASE_BACKOFF_SECONDS = 60.0
_MAX_BACKOFF_SECONDS = 3600.0
_GIVE_UP_AFTER_ATTEMPTS = 5

AttemptState = dict[str, dict[str, object]]


def _backoff_seconds(fail_count: int) -> float:
    return min(_MAX_BACKOFF_SECONDS, _BASE_BACKOFF_SECONDS * (2 ** (fail_count - 1)))


def _record_failure(state: AttemptState, thread_id: str, *, last_client_message_id: str | None, now: float) -> int:
    """Bump *thread_id*'s failure count and set its next-retry time; returns the new count."""
    fail_count = int(state[thread_id]["fail_count"]) + 1 if thread_id in state else 1
    state[thread_id] = {"fail_count": fail_count, "next_retry_at": now + _backoff_seconds(fail_count), "last_client_message_id": last_client_message_id}
    return fail_count


async def run_concierge_pass(
    board_repo,
    *,
    app_config: AppConfig | None = None,
    model_name: str | None = None,
    generate_draft: GenerateDraft | None = None,
    audit_repo=None,
    attempt_state: AttemptState | None = None,
    now: float | None = None,
) -> list[str]:
    """Draft a reply once for every ``new``/``triaged`` thread that has one.

    Only ever writes a ``momo`` draft message and the ``drafted`` transition
    -- never approves or replies. A thread whose status changed by the time
    the write lands (raced with another actor, or another concierge pass
    under multiple Gateway workers), whose draft generation returned
    nothing, or that raised anywhere in its own handling, is left untouched
    and does not stop the rest of the pass. Drafts against the thread's
    latest *client* message, and skips a thread whose latest message is
    already a ``momo`` draft (an untouched or rejected-and-not-yet-replied-to
    draft) so a rejected draft is never duplicated and a stale draft is
    never re-answered instead of the client's actual latest message.
    Returns the ids of threads drafted this pass.

    *attempt_state*, if given, is a caller-owned dict this function mutates:
    a thread that fails to draft (empty result or an exception) gets an
    exponential backoff (capped at an hour) before it is tried again, reset
    whenever the thread's latest client message id changes (a genuine new
    client message -- *not* ``BoardThreadRow.updated_at``, which
    ``BoardRepository.add_message`` never touches, so it cannot signal "a
    new message arrived"), and a warning is logged once when a thread
    crosses ``_GIVE_UP_AFTER_ATTEMPTS`` consecutive failures -- without
    this, a thread that always fails to draft (a content filter, an
    oversized context) would cost one full model call every single pass
    forever. Pass ``now`` (a ``time.monotonic()`` value) for deterministic
    tests; defaults to the real clock.

    When *audit_repo* is given (an ``AuditEventRepository``), each
    successful draft also records a ``board.thread.concierge_drafted`` audit
    event -- in its own try/except, so a failure recording the event (never
    expected: ``AuditEventRepository.record`` already swallows its own
    errors) cannot be mislabeled as a failure to draft the thread, which did
    already succeed by that point.
    """
    draft_fn = generate_draft or generate_draft_body
    state = attempt_state if attempt_state is not None else {}
    clock = now if now is not None else time.monotonic()
    drafted_ids: list[str] = []
    for status in _DRAFT_ELIGIBLE_STATUSES:
        threads = await board_repo.list_threads(status=status)
        for thread in threads:
            thread_id = thread["id"]
            last_client_message_id: str | None = None
            try:
                messages = await board_repo.list_messages(thread_id) or []
                last_client_index = None
                last_momo_index = None
                for i, message in enumerate(messages):
                    if message["author_kind"] == "client":
                        last_client_index = i
                    elif message["author_kind"] == "momo":
                        last_momo_index = i
                if last_client_index is None:
                    continue  # nothing from the client yet to draft against
                if last_momo_index is not None and last_momo_index > last_client_index:
                    continue
                last_client_message_id = messages[last_client_index]["id"]

                entry = state.get(thread_id)
                if entry is not None and entry["last_client_message_id"] != last_client_message_id:
                    # A genuine new client message since the last failure:
                    # forget the old failure history and try again now.
                    state.pop(thread_id, None)
                    entry = None
                if entry is not None and clock < entry["next_retry_at"]:
                    continue  # still backing off from repeated failures

                content = messages[last_client_index]["body"]
                draft = await draft_fn(
                    content,
                    subject=thread.get("subject", ""),
                    kind=thread.get("kind", ""),
                    app_config=app_config,
                    model_name=model_name,
                )
                if not draft:
                    fail_count = _record_failure(state, thread_id, last_client_message_id=last_client_message_id, now=clock)
                    if fail_count == _GIVE_UP_AFTER_ATTEMPTS:
                        logger.warning("Board concierge giving up on thread %s after %d failed draft attempts (backing off up to %.0fs between tries)", thread_id, fail_count, _MAX_BACKOFF_SECONDS)
                    continue

                updated = await board_repo.try_add_momo_draft(thread_id, from_statuses=_DRAFT_ELIGIBLE_STATUSES, body=draft)
                if updated is None:
                    continue

                state.pop(thread_id, None)
                drafted_ids.append(thread_id)
            except Exception:
                _record_failure(state, thread_id, last_client_message_id=last_client_message_id, now=clock)
                logger.warning("Board concierge failed to draft thread %s; left for the next pass", thread_id, exc_info=True)
                continue

            if audit_repo is not None:
                try:
                    await audit_repo.record(
                        action="board.thread.concierge_drafted",
                        outcome="success",
                        actor_user_id=None,
                        organization_id=thread.get("organization_id"),
                        target_type="board_thread",
                        target_id=thread_id,
                    )
                except Exception:
                    logger.warning("Board concierge drafted thread %s but failed to record its audit event", thread_id, exc_info=True)

    return drafted_ids
