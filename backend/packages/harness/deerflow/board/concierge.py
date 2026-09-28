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


async def run_concierge_pass(
    board_repo,
    *,
    app_config: AppConfig | None = None,
    model_name: str | None = None,
    generate_draft: GenerateDraft | None = None,
    audit_repo=None,
) -> list[str]:
    """Draft a reply once for every ``new``/``triaged`` thread that has one.

    Only ever writes a ``momo`` draft message and the ``drafted`` transition
    -- never approves or replies. A thread whose status changed by the time
    the write lands (raced with another actor, or another concierge pass
    under multiple Gateway workers), whose draft generation returned
    nothing, or that raised anywhere in its own handling, is left untouched
    and does not stop the rest of the pass. Returns the ids of threads
    drafted this pass. When *audit_repo* is given (an
    ``AuditEventRepository``), each successful draft also records a
    ``board.thread.concierge_drafted`` audit event.
    """
    draft_fn = generate_draft or generate_draft_body
    drafted_ids: list[str] = []
    for status in _DRAFT_ELIGIBLE_STATUSES:
        threads = await board_repo.list_threads(status=status)
        for thread in threads:
            thread_id = thread["id"]
            try:
                messages = await board_repo.list_messages(thread_id) or []
                content = messages[0]["body"] if messages else thread.get("subject", "")
                draft = await draft_fn(
                    content,
                    subject=thread.get("subject", ""),
                    kind=thread.get("kind", ""),
                    app_config=app_config,
                    model_name=model_name,
                )
                if not draft:
                    continue

                updated = await board_repo.try_add_momo_draft(thread_id, from_statuses=_DRAFT_ELIGIBLE_STATUSES, body=draft)
                if updated is None:
                    continue

                drafted_ids.append(thread_id)
                if audit_repo is not None:
                    await audit_repo.record(
                        action="board.thread.concierge_drafted",
                        outcome="success",
                        actor_user_id=None,
                        organization_id=thread.get("organization_id"),
                        target_type="board_thread",
                        target_id=thread_id,
                    )
            except Exception:
                logger.warning("Board concierge failed to draft thread %s; left for the next pass", thread_id, exc_info=True)

    return drafted_ids
