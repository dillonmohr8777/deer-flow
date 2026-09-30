"""Fleet-agent tool that drafts a Momo Board post for a client (queue item e13,
the "Plan a big project" starter's payoff).

Gated behind the ``deliberate`` tool group in an agent's ``config.yaml`` --
the same three engineer roles Dillon named for ``deliberate`` ("especially
engineers") get this tool too, so a role that plans a big project can also
propose it to the client without a second product decision about who gets
it. Momentum-staff only, mirroring every other tool in that group.

Unlike ``deliberate`` this tool has no client-data restriction: it does not
send anything anywhere by itself. It only writes a *draft* -- the same
``drafted`` state ``POST /api/board/threads/{id}/draft`` produces -- so the
plan lands in the organization owner's existing Board/Desk approvals queue
and only reaches the client once a human owner explicitly approves and sends
it (``deerflow.board.workflow``'s ``approved``/``replied`` steps, both still
owner-only via the HTTP router). This tool is, in effect, the "separate
internal Momo caller" that ``board.py``'s ``assert_can_draft`` docstring
notes doesn't exist yet for the human endpoint: it goes straight to the
``BoardRepository``, not through the HTTP router's owner-authenticated
``draft_board_reply``, since a fleet-agent tool call has no acting HTTP user
to check for owner/admin standing in the first place.
"""

from __future__ import annotations

from langchain.tools import tool

from deerflow.persistence.board.model import BoardThreadKind, BoardThreadStatus
from deerflow.runtime.user_context import resolve_organization_id
from deerflow.tools.exec_seat_tools import _is_momentum_staff_run
from deerflow.tools.types import Runtime

_MAX_SUBJECT_CHARS = 200
_MAX_BODY_CHARS = 20000


def _error(message: str) -> dict:
    return {"error": message}


def _staff_only_error() -> dict:
    return _error("Board draft tools are restricted to Momentum staff.")


def _get_board_repo():
    """Lazy import so a test's monkeypatched session factory takes effect."""
    from deerflow.persistence.board import BoardRepository
    from deerflow.persistence.engine import get_session_factory

    session_factory = get_session_factory()
    if session_factory is None:
        return None
    return BoardRepository(session_factory)


def _get_client_repo():
    from deerflow.persistence.clients import ClientRepository
    from deerflow.persistence.engine import get_session_factory

    session_factory = get_session_factory()
    if session_factory is None:
        return None
    return ClientRepository(session_factory)


async def _draft_board_thread_impl(client_id: str, subject: str, body: str, *, runtime: Runtime | None = None) -> dict:
    if not _is_momentum_staff_run(runtime):
        return _staff_only_error()
    if resolve_organization_id() is None:
        return _error("Board draft tools require an organization context.")
    if not client_id or not client_id.strip():
        return _error("client_id is required.")
    if not body or not body.strip():
        return _error("body is required.")
    if len(subject) > _MAX_SUBJECT_CHARS:
        return _error(f"subject is too long. Keep it under {_MAX_SUBJECT_CHARS} characters.")
    if len(body) > _MAX_BODY_CHARS:
        return _error(f"body is too long. Keep it under {_MAX_BODY_CHARS} characters.")

    client_repo = _get_client_repo()
    board_repo = _get_board_repo()
    if client_repo is None or board_repo is None:
        return _error("Board storage is unavailable.")

    client = await client_repo.get(client_id)
    if client is None:
        return _error("No such client in this organization.")

    thread = await board_repo.create_thread(client_id=client_id, kind=BoardThreadKind.POST, subject=subject, created_by_user_id=None)
    await board_repo.add_message(thread["id"], author_kind="momo", author_user_id=None, body=body)
    updated = await board_repo.patch_thread(thread["id"], status=BoardThreadStatus.DRAFTED)
    if updated is None:
        return _error("Failed to draft the board thread.")
    return {"thread_id": updated["id"], "status": updated["status"]}


@tool(parse_docstring=True)
async def draft_board_thread(client_id: str, subject: str, body: str, runtime: Runtime) -> dict:
    """Draft a Momo Board post proposing a plan to a client, for owner approval.

    Momentum-staff only, like the team/exec/hire/deliberate tool groups. Use
    this once a big-project plan is ready to propose -- it never sends
    anything to the client by itself: it only creates a Board thread already
    in the "drafted" state, the same state a human's own draft action
    produces, so it appears in the organization owner's approvals queue and
    waits there until the owner explicitly approves and sends it.

    Args:
        client_id: The Momo Board client this plan is for.
        subject: A short subject line for the thread, shown in listings.
        body: The plan message Momo is proposing to send once approved.
        runtime: Injected tool runtime.

    Returns:
        {"thread_id", "status"} on success, or {"error": ...}.
    """
    return await _draft_board_thread_impl(client_id, subject, body, runtime=runtime)
