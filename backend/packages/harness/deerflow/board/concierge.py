"""Momo Board draft concierge (Workspace Phase 4 item e5).

Behind ``config.board.concierge_enabled`` (default off), a background loop
drafts a reply for every ``new``/``triaged`` board thread and moves it to
``drafted`` through the same ``assert_can_draft`` gate the
``/threads/{id}/draft`` route uses (``deerflow.board.workflow``,
``app/gateway/routers/board.py::draft_board_reply``). This module never
calls ``assert_can_approve``/``assert_can_reply`` and makes no write beyond
that one draft message plus the ``drafted`` status transition -- an owner
must still approve and send.

Draft generation mirrors ``deerflow.board.triage``'s LLM plumbing
(``create_chat_model`` + ``ainvoke``, no persistence dependency of its own)
and is injectable via ``generate_draft`` the same way tests stub
``triage_board_thread``'s model call.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Awaitable, Callable

from deerflow.board.workflow import BoardTransitionError, assert_can_draft
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
) -> list[str]:
    """Draft a reply once for every ``new``/``triaged`` thread that has one.

    Only ever writes a ``momo`` draft message and the ``drafted`` transition
    -- never approves or replies. A thread whose status changed since the
    listing (raced with another actor) or whose draft generation returned
    nothing is left untouched. Returns the ids of threads drafted this pass.
    """
    draft_fn = generate_draft or generate_draft_body
    drafted_ids: list[str] = []
    for status in _DRAFT_ELIGIBLE_STATUSES:
        threads = await board_repo.list_threads(status=status)
        for thread in threads:
            thread_id = thread["id"]
            try:
                assert_can_draft(thread["status"])
            except BoardTransitionError:
                continue

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

            await board_repo.add_message(thread_id, author_kind="momo", author_user_id=None, body=draft)
            updated = await board_repo.patch_thread(thread_id, status=BoardThreadStatus.DRAFTED)
            if updated is not None:
                drafted_ids.append(thread_id)

    return drafted_ids
