"""CRUD API for the Momo Board (Workspace Phase 4 item b2): client posts,
tickets, concerns and DMs, plus their message history.

Route permissions mirror ``clients.py`` (read/write, org-scoped repository).
On top of the organization boundary the repository already enforces,
every route here additionally checks per-client access: an organization
owner/admin sees every thread, anyone else must hold a ``client_assignments``
row for the thread's client -- otherwise the thread is treated as missing,
mirroring ``clients.py``'s ``_require_stamp_authorized`` and its
"foreign is indistinguishable from missing" 404 convention.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.gateway.authz import require_permission
from app.gateway.deps import get_board_repo, get_client_repo, get_current_user_from_request, record_audit_event
from deerflow.board.triage import triage_board_thread
from deerflow.board.workflow import BoardOwnerRequiredError, BoardTransitionError, assert_can_approve, assert_can_draft, assert_can_reply
from deerflow.persistence.board.model import BoardThreadStatus
from deerflow.persistence.organizations.model import OrganizationMemberRow
from deerflow.runtime.user_context import resolve_organization_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/board", tags=["board"])

# Bounds the triage-on-create model call so a hung provider can't hang thread
# creation; a timeout is treated the same as any other triage failure.
_TRIAGE_TIMEOUT_SECONDS = 20

_ORG_ADMIN_ROLES = ("owner", "admin")

BoardKind = Literal["post", "ticket", "concern", "dm"]
BoardStatus = Literal["new", "triaged", "drafted", "approved", "replied", "closed"]


class BoardThreadResponse(BaseModel):
    id: str
    client_id: str | None
    kind: str
    status: str
    subject: str
    urgency: str | None = None
    summary: str | None = None
    created_by_user_id: str | None
    created_at: str
    updated_at: str


class BoardThreadListResponse(BaseModel):
    threads: list[BoardThreadResponse]


class BoardThreadCreateRequest(BaseModel):
    client_id: str = Field(..., min_length=1)
    kind: BoardKind = "post"
    subject: str = ""


class BoardThreadPatchRequest(BaseModel):
    status: BoardStatus | None = None
    subject: str | None = None


class BoardMessageResponse(BaseModel):
    id: str
    thread_id: str
    author_kind: str
    author_user_id: str | None
    body: str
    created_at: str


class BoardMessageListResponse(BaseModel):
    messages: list[BoardMessageResponse]


class BoardMessageCreateRequest(BaseModel):
    body: str = Field(..., min_length=1)


class BoardDraftRequest(BaseModel):
    body: str = Field(..., min_length=1)


class BoardReplyRequest(BaseModel):
    body: str = Field(..., min_length=1)


def _not_found() -> HTTPException:
    # Fail closed: a foreign or missing thread/client looks the same to the caller.
    return HTTPException(status_code=404, detail="Board thread not found")


def _to_thread_response(row: dict, *, actor_is_owner: bool) -> BoardThreadResponse:
    # Momo's triage (urgency/summary) is internal shorthand -- it can read like
    # "INTERNAL: client is angry, churn risk" -- so only an org owner/admin
    # ever sees it, the same boundary list_board_messages already draws around
    # a still-unapproved momo draft.
    return BoardThreadResponse(
        id=row["id"],
        client_id=row.get("client_id"),
        kind=row["kind"],
        status=row["status"],
        subject=row.get("subject", ""),
        urgency=row.get("urgency") if actor_is_owner else None,
        summary=row.get("summary") if actor_is_owner else None,
        created_by_user_id=row.get("created_by_user_id"),
        created_at=row.get("created_at", ""),
        updated_at=row.get("updated_at", ""),
    )


def _to_message_response(row: dict) -> BoardMessageResponse:
    return BoardMessageResponse(
        id=row["id"],
        thread_id=row["thread_id"],
        author_kind=row["author_kind"],
        author_user_id=row.get("author_user_id"),
        body=row.get("body", ""),
        created_at=row.get("created_at", ""),
    )


async def _is_active_org_admin(user_id: str) -> bool:
    """Whether *user_id* is an active owner/admin of the caller's active organization.

    Mirrors ``clients.py``'s helper of the same name.
    """
    organization_id = resolve_organization_id()
    if organization_id is None:
        return False
    # Lazy import: resolved at call time so a test's
    # ``monkeypatch.setattr("deerflow.persistence.engine.get_session_factory", ...)``
    # takes effect, matching ``clients.py``.
    from deerflow.persistence.engine import get_session_factory

    session_factory = get_session_factory()
    if session_factory is None:
        return False
    stmt = select(OrganizationMemberRow.user_id).where(
        OrganizationMemberRow.organization_id == organization_id,
        OrganizationMemberRow.user_id == user_id,
        OrganizationMemberRow.status == "active",
        OrganizationMemberRow.role.in_(_ORG_ADMIN_ROLES),
    )
    async with session_factory() as session:
        return (await session.execute(stmt)).scalars().first() is not None


async def _thread_delivered(board_repo, thread_id: str) -> bool:
    """Whether *thread_id* has ever carried a message stamped ``delivered_at``.

    f157 rounds 2-3: neither a thread's *current* status nor a message's
    ``author_kind`` safely proves "this shipped to the client". Status fails
    because ``patch_board_thread`` lets an org admin set ``new``/``triaged``/
    ``closed`` from any status at any time (only ``drafted``/``approved``/
    ``replied`` are workflow-only), so a rejected or superseded draft can
    land back on a status that looks "approved" by a purely status-based
    rule. ``author_kind == "owner"`` fails because ``add_board_message``
    lets any org admin post an internal note with that same author kind
    (e.g. review feedback on a still-unapproved draft) -- that is not a
    delivery. Only ``send_board_reply`` ever stamps ``delivered_at`` (see
    ``BoardRepository.thread_ids_with_delivered_message``), so its mere
    existence is what actually proves something on this thread shipped.
    """
    return thread_id in await board_repo.thread_ids_with_delivered_message([thread_id])


def _visible_to_non_admin(row: dict, *, delivered: bool) -> bool:
    """Whether a non-admin with client access may see thread/row *row* at all.

    A thread a real person started (``created_by_user_id`` is set, e.g. a
    client's own post or an owner's) is always visible to its assigned
    client -- they already know it exists. A thread a fleet-agent tool
    created on Momo's behalf (``created_by_user_id`` is ``None`` --
    ``draft_board_thread`` is the only such caller today) starts life
    holding nothing but an unapproved internal draft, and must stay
    invisible -- thread and messages both -- until it has actually been
    delivered (f157): otherwise a client contact can read a plan that was
    never meant to reach them yet, or even learn one exists.
    """
    return row.get("created_by_user_id") is not None or delivered


async def _require_client_access(client_repo, client_id: str, user_id: str) -> None:
    """Raise 404 unless *user_id* is an org admin or assigned to *client_id*."""
    if await client_repo.get(client_id) is None:
        raise _not_found()
    if await _is_active_org_admin(user_id):
        return
    mine_ids = {c["id"] for c in await client_repo.list_mine()}
    if client_id not in mine_ids:
        raise _not_found()


async def _require_thread_access(board_repo, client_repo, row: dict, user_id: str) -> None:
    """Raise 404 unless *user_id* may act on the loaded thread *row*.

    A client-stamped thread follows ``_require_client_access``, plus the
    tool-created-and-not-yet-delivered check (f157) -- see
    ``_visible_to_non_admin``. A thread with no client (f66) is
    owner/admin-only: no client assignment can grant it, so without this
    every org member, including a client-role account, could read and write it.
    """
    client_id = row.get("client_id")
    if client_id is None:
        if not await _is_active_org_admin(user_id):
            raise _not_found()
        return
    if await _is_active_org_admin(user_id):
        await _require_client_access(client_repo, client_id, user_id)
        return
    if row.get("created_by_user_id") is None and not await _thread_delivered(board_repo, row["id"]):
        raise _not_found()
    await _require_client_access(client_repo, client_id, user_id)


@router.post("/threads", response_model=BoardThreadResponse, status_code=201)
@require_permission("board", "write")
async def create_board_thread(body: BoardThreadCreateRequest, request: Request) -> BoardThreadResponse:
    client_repo = get_client_repo(request)
    board_repo = get_board_repo(request)
    user = await get_current_user_from_request(request)
    await _require_client_access(client_repo, body.client_id, str(user.id))
    row = await board_repo.create_thread(client_id=body.client_id, kind=body.kind, subject=body.subject, created_by_user_id=str(user.id))
    try:
        triage = await asyncio.wait_for(triage_board_thread(body.subject), timeout=_TRIAGE_TIMEOUT_SECONDS)
        if not triage.fallback:
            # Only a real classification is worth recording: a fallback
            # result must never look indistinguishable from Momo actually
            # having triaged the thread -- e4/e5 read these columns as fact,
            # and the thread should stay `new` (unclassified) so something
            # retries it later instead of silently reading as "normal".
            updated = await board_repo.patch_thread(row["id"], status=BoardThreadStatus.TRIAGED, urgency=triage.urgency, summary=triage.summary)
            if updated is not None:
                row = updated
    except Exception:
        # Triage is an aid, not a gate: never let a classification failure or
        # timeout (triage_board_thread's own model-call failures are already
        # handled inside it -- this catches anything else in the path, e.g. a
        # hung provider outrunning the timeout above, or the DB patch itself)
        # turn a created thread into a 500.
        logger.warning("Board triage-on-create failed; thread created without a triage classification", exc_info=True)
    actor_is_owner = await _is_active_org_admin(str(user.id))
    return _to_thread_response(row, actor_is_owner=actor_is_owner)


@router.get("/threads", response_model=BoardThreadListResponse)
@require_permission("board", "read")
async def list_board_threads(request: Request, client_id: str | None = None, status: BoardStatus | None = None) -> BoardThreadListResponse:
    client_repo = get_client_repo(request)
    board_repo = get_board_repo(request)
    user = await get_current_user_from_request(request)
    user_id = str(user.id)
    actor_is_owner = await _is_active_org_admin(user_id)
    if client_id is not None:
        await _require_client_access(client_repo, client_id, user_id)
        rows = await board_repo.list_threads(client_id=client_id, status=status)
    elif actor_is_owner:
        rows = await board_repo.list_threads(status=status)
    else:
        mine_ids = [c["id"] for c in await client_repo.list_mine()]
        rows = await board_repo.list_threads(client_ids=mine_ids, status=status) if mine_ids else []
    if not actor_is_owner:
        pending_ids = [r["id"] for r in rows if r.get("created_by_user_id") is None]
        delivered_ids = await board_repo.thread_ids_with_delivered_message(pending_ids)
        rows = [r for r in rows if _visible_to_non_admin(r, delivered=r["id"] in delivered_ids)]
    return BoardThreadListResponse(threads=[_to_thread_response(r, actor_is_owner=actor_is_owner) for r in rows])


@router.get("/threads/{thread_id}", response_model=BoardThreadResponse)
@require_permission("board", "read")
async def get_board_thread(thread_id: str, request: Request) -> BoardThreadResponse:
    board_repo = get_board_repo(request)
    client_repo = get_client_repo(request)
    row = await board_repo.get_thread(thread_id)
    if row is None:
        raise _not_found()
    user = await get_current_user_from_request(request)
    await _require_thread_access(board_repo, client_repo, row, str(user.id))
    actor_is_owner = await _is_active_org_admin(str(user.id))
    return _to_thread_response(row, actor_is_owner=actor_is_owner)


_WORKFLOW_ONLY_STATUSES = frozenset({BoardThreadStatus.DRAFTED, BoardThreadStatus.APPROVED, BoardThreadStatus.REPLIED})


@router.patch("/threads/{thread_id}", response_model=BoardThreadResponse)
@require_permission("board", "write")
async def patch_board_thread(thread_id: str, body: BoardThreadPatchRequest, request: Request) -> BoardThreadResponse:
    """A direct status write can't reach ``drafted``/``approved``/``replied`` -- those are
    workflow-only (``draft``/``approve``/``reply``), which is what ``send_board_reply``'s
    "latest momo draft" check relies on actually having gone through. Any other status
    change still requires an org owner/admin, checked before the workflow-only gate so a
    non-admin's forged transition is an audited denial, not a bare 409.
    """
    board_repo = get_board_repo(request)
    client_repo = get_client_repo(request)
    row = await board_repo.get_thread(thread_id)
    if row is None:
        raise _not_found()
    user = await get_current_user_from_request(request)
    user_id = str(user.id)
    await _require_thread_access(board_repo, client_repo, row, user_id)
    if body.status is not None:
        if not await _is_active_org_admin(user_id):
            await record_audit_event(request, action="board.thread.status_patch", outcome="denied", actor_user_id=user_id, organization_id=resolve_organization_id(), target_type="board_thread", target_id=thread_id)
            raise HTTPException(status_code=403, detail="Only an organization owner/admin may change a board thread's status")
        if body.status in _WORKFLOW_ONLY_STATUSES:
            raise HTTPException(status_code=409, detail=f"Status {body.status!r} can only be reached through the draft/approve/reply workflow")
    updated = await board_repo.patch_thread(thread_id, status=body.status, subject=body.subject)
    if updated is None:
        raise _not_found()
    if body.status is not None:
        await record_audit_event(request, action="board.thread.status_patch", outcome="success", actor_user_id=user_id, organization_id=resolve_organization_id(), target_type="board_thread", target_id=thread_id)
    actor_is_owner = await _is_active_org_admin(user_id)
    return _to_thread_response(updated, actor_is_owner=actor_is_owner)


@router.get("/threads/{thread_id}/messages", response_model=BoardMessageListResponse)
@require_permission("board", "read")
async def list_board_messages(thread_id: str, request: Request) -> BoardMessageListResponse:
    board_repo = get_board_repo(request)
    client_repo = get_client_repo(request)
    row = await board_repo.get_thread(thread_id)
    if row is None:
        raise _not_found()
    user = await get_current_user_from_request(request)
    user_id = str(user.id)
    await _require_thread_access(board_repo, client_repo, row, user_id)
    messages = await board_repo.list_messages(thread_id) or []
    if not await _is_active_org_admin(user_id):
        # A non-admin never sees momo's own raw message, approved or not:
        # whatever actually ships to the client is always separately written
        # as an `owner`-authored message by `send_board_reply` (`:479`), so
        # the momo draft itself has nothing a client needs to read. This is
        # deliberately unconditional (not keyed on thread status, f157 round
        # 2) -- status can be walked back to new/triaged/closed by a PATCH at
        # any time, so it can never safely stand in for "was this approved".
        #
        # An `owner`-authored message additionally needs `delivered_at` set
        # (f175): `add_board_message` (`:372`) lets an admin post an internal
        # note with that same author kind, e.g. review feedback on a
        # still-unapproved draft -- once the thread later becomes visible
        # (a real reply ships), that earlier note must not ride along just
        # because it shares `author_kind == "owner"` with the delivered one.
        messages = [m for m in messages if m["author_kind"] == "client" or (m["author_kind"] == "owner" and m.get("delivered_at") is not None)]
    return BoardMessageListResponse(messages=[_to_message_response(m) for m in messages])


@router.post("/threads/{thread_id}/messages", response_model=BoardMessageResponse, status_code=201)
@require_permission("board", "write")
async def add_board_message(thread_id: str, body: BoardMessageCreateRequest, request: Request) -> BoardMessageResponse:
    """``author_kind`` is derived server-side, never taken from the request body.

    A caller cannot label their own message ``momo`` (or someone else's
    ``owner``): only ``draft_board_reply``'s own ``add_message`` call ever
    writes a ``momo``-authored message, which is what ``send_board_reply``
    relies on when it checks a reply against "the latest momo draft".
    """
    board_repo = get_board_repo(request)
    client_repo = get_client_repo(request)
    row = await board_repo.get_thread(thread_id)
    if row is None:
        raise _not_found()
    user = await get_current_user_from_request(request)
    user_id = str(user.id)
    await _require_thread_access(board_repo, client_repo, row, user_id)
    author_kind = "owner" if await _is_active_org_admin(user_id) else "client"
    message = await board_repo.add_message(thread_id, author_kind=author_kind, author_user_id=user_id, body=body.body)
    if message is None:
        raise _not_found()
    return _to_message_response(message)


async def _latest_momo_draft_body(board_repo, thread_id: str) -> str | None:
    """The body of the most recent ``momo``-authored message, or ``None`` if there is none."""
    messages = await board_repo.list_messages(thread_id) or []
    for message in reversed(messages):
        if message["author_kind"] == "momo":
            return message.get("body")
    return None


async def _load_thread_for_actor(board_repo, client_repo, thread_id: str, request: Request) -> tuple[dict, str]:
    """Fetch *thread_id*, enforcing per-client access; returns ``(row, actor_user_id)``."""
    row = await board_repo.get_thread(thread_id)
    if row is None:
        raise _not_found()
    user = await get_current_user_from_request(request)
    user_id = str(user.id)
    await _require_thread_access(board_repo, client_repo, row, user_id)
    return row, user_id


@router.post("/threads/{thread_id}/draft", response_model=BoardThreadResponse)
@require_permission("board", "write")
async def draft_board_reply(thread_id: str, body: BoardDraftRequest, request: Request) -> BoardThreadResponse:
    """Momo drafts a reply: adds a ``momo``-authored message and moves the thread to ``drafted``.

    There is no separate internal "Momo" caller yet, so this endpoint is
    reachable by any authenticated org member with client access -- gated to
    an org owner/admin the same way ``approve``/``reply`` are, so a plain
    client-assigned member can't write their own text into what ``reply``
    treats as the approved draft.
    """
    board_repo = get_board_repo(request)
    client_repo = get_client_repo(request)
    row, user_id = await _load_thread_for_actor(board_repo, client_repo, thread_id, request)
    actor_is_owner = await _is_active_org_admin(user_id)
    try:
        assert_can_draft(row["status"], actor_is_owner=actor_is_owner)
    except BoardOwnerRequiredError as exc:
        await record_audit_event(request, action="board.thread.draft", outcome="denied", actor_user_id=user_id, organization_id=resolve_organization_id(), target_type="board_thread", target_id=thread_id)
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except BoardTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await board_repo.add_message(thread_id, author_kind="momo", author_user_id=None, body=body.body)
    updated = await board_repo.patch_thread(thread_id, status=BoardThreadStatus.DRAFTED)
    if updated is None:
        raise _not_found()
    await record_audit_event(request, action="board.thread.drafted", outcome="success", actor_user_id=user_id, organization_id=resolve_organization_id(), target_type="board_thread", target_id=thread_id)
    actor_is_owner = await _is_active_org_admin(user_id)
    return _to_thread_response(updated, actor_is_owner=actor_is_owner)


@router.post("/threads/{thread_id}/approve", response_model=BoardThreadResponse)
@require_permission("board", "write")
async def approve_board_reply(thread_id: str, request: Request) -> BoardThreadResponse:
    """Only an org owner/admin may move a drafted reply to ``approved``."""
    board_repo = get_board_repo(request)
    client_repo = get_client_repo(request)
    row, user_id = await _load_thread_for_actor(board_repo, client_repo, thread_id, request)
    actor_is_owner = await _is_active_org_admin(user_id)
    try:
        assert_can_approve(row["status"], actor_is_owner=actor_is_owner)
    except BoardOwnerRequiredError as exc:
        await record_audit_event(request, action="board.thread.approve", outcome="denied", actor_user_id=user_id, organization_id=resolve_organization_id(), target_type="board_thread", target_id=thread_id)
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except BoardTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    updated = await board_repo.patch_thread(thread_id, status=BoardThreadStatus.APPROVED)
    if updated is None:
        raise _not_found()
    await record_audit_event(request, action="board.thread.approved", outcome="success", actor_user_id=user_id, organization_id=resolve_organization_id(), target_type="board_thread", target_id=thread_id)
    return _to_thread_response(updated, actor_is_owner=actor_is_owner)


@router.post("/threads/{thread_id}/reply", response_model=BoardThreadResponse)
@require_permission("board", "write")
async def send_board_reply(thread_id: str, body: BoardReplyRequest, request: Request) -> BoardThreadResponse:
    """``replied`` needs its own explicit owner action, separate from ``approve``.

    The sent body must match the approved draft verbatim -- an owner's approval
    stamps a specific message, not a blank check to send anything under it. A
    body that differs from the latest ``momo`` draft is rejected rather than
    silently substituted or accepted, and so is a reply with no draft to check
    against at all (fail closed, not open): reaching ``approved`` with no
    ``momo`` message on the thread is not a state this router's own workflow
    can produce, so it is treated the same as a mismatch rather than let through.
    """
    board_repo = get_board_repo(request)
    client_repo = get_client_repo(request)
    row, user_id = await _load_thread_for_actor(board_repo, client_repo, thread_id, request)
    actor_is_owner = await _is_active_org_admin(user_id)
    try:
        assert_can_reply(row["status"], actor_is_owner=actor_is_owner)
    except BoardOwnerRequiredError as exc:
        await record_audit_event(request, action="board.thread.reply", outcome="denied", actor_user_id=user_id, organization_id=resolve_organization_id(), target_type="board_thread", target_id=thread_id)
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except BoardTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    draft_body = await _latest_momo_draft_body(board_repo, thread_id)
    if draft_body is None or body.body.strip() != draft_body.strip():
        await record_audit_event(request, action="board.thread.reply", outcome="denied", actor_user_id=user_id, organization_id=resolve_organization_id(), target_type="board_thread", target_id=thread_id)
        raise HTTPException(status_code=409, detail="Reply body must match the approved draft verbatim; edit the draft and re-approve instead")
    await board_repo.add_message(thread_id, author_kind="owner", author_user_id=user_id, body=draft_body, delivered=True)
    updated = await board_repo.patch_thread(thread_id, status=BoardThreadStatus.REPLIED)
    if updated is None:
        raise _not_found()
    await record_audit_event(request, action="board.thread.replied", outcome="success", actor_user_id=user_id, organization_id=resolve_organization_id(), target_type="board_thread", target_id=thread_id)
    return _to_thread_response(updated, actor_is_owner=actor_is_owner)
