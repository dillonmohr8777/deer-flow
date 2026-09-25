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

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.gateway.authz import require_permission
from app.gateway.deps import get_board_repo, get_client_repo, get_current_user_from_request, record_audit_event
from deerflow.board.workflow import BoardOwnerRequiredError, BoardTransitionError, assert_can_approve, assert_can_draft, assert_can_reply
from deerflow.persistence.board.model import BoardThreadStatus
from deerflow.persistence.organizations.model import OrganizationMemberRow
from deerflow.runtime.user_context import resolve_organization_id

router = APIRouter(prefix="/api/board", tags=["board"])

_ORG_ADMIN_ROLES = ("owner", "admin")

BoardKind = Literal["post", "ticket", "concern", "dm"]
BoardStatus = Literal["new", "triaged", "drafted", "approved", "replied", "closed"]


class BoardThreadResponse(BaseModel):
    id: str
    client_id: str | None
    kind: str
    status: str
    subject: str
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


def _to_thread_response(row: dict) -> BoardThreadResponse:
    return BoardThreadResponse(
        id=row["id"],
        client_id=row.get("client_id"),
        kind=row["kind"],
        status=row["status"],
        subject=row.get("subject", ""),
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


async def _require_client_access(client_repo, client_id: str, user_id: str) -> None:
    """Raise 404 unless *user_id* is an org admin or assigned to *client_id*."""
    if await client_repo.get(client_id) is None:
        raise _not_found()
    if await _is_active_org_admin(user_id):
        return
    mine_ids = {c["id"] for c in await client_repo.list_mine()}
    if client_id not in mine_ids:
        raise _not_found()


@router.post("/threads", response_model=BoardThreadResponse, status_code=201)
@require_permission("board", "write")
async def create_board_thread(body: BoardThreadCreateRequest, request: Request) -> BoardThreadResponse:
    client_repo = get_client_repo(request)
    board_repo = get_board_repo(request)
    user = await get_current_user_from_request(request)
    await _require_client_access(client_repo, body.client_id, str(user.id))
    row = await board_repo.create_thread(client_id=body.client_id, kind=body.kind, subject=body.subject, created_by_user_id=str(user.id))
    return _to_thread_response(row)


@router.get("/threads", response_model=BoardThreadListResponse)
@require_permission("board", "read")
async def list_board_threads(request: Request, client_id: str | None = None, status: BoardStatus | None = None) -> BoardThreadListResponse:
    client_repo = get_client_repo(request)
    board_repo = get_board_repo(request)
    user = await get_current_user_from_request(request)
    user_id = str(user.id)
    if client_id is not None:
        await _require_client_access(client_repo, client_id, user_id)
        rows = await board_repo.list_threads(client_id=client_id, status=status)
    elif await _is_active_org_admin(user_id):
        rows = await board_repo.list_threads(status=status)
    else:
        mine_ids = [c["id"] for c in await client_repo.list_mine()]
        rows = await board_repo.list_threads(client_ids=mine_ids, status=status) if mine_ids else []
    return BoardThreadListResponse(threads=[_to_thread_response(r) for r in rows])


@router.get("/threads/{thread_id}", response_model=BoardThreadResponse)
@require_permission("board", "read")
async def get_board_thread(thread_id: str, request: Request) -> BoardThreadResponse:
    board_repo = get_board_repo(request)
    client_repo = get_client_repo(request)
    row = await board_repo.get_thread(thread_id)
    if row is None:
        raise _not_found()
    user = await get_current_user_from_request(request)
    if row.get("client_id") is not None:
        await _require_client_access(client_repo, row["client_id"], str(user.id))
    return _to_thread_response(row)


@router.patch("/threads/{thread_id}", response_model=BoardThreadResponse)
@require_permission("board", "write")
async def patch_board_thread(thread_id: str, body: BoardThreadPatchRequest, request: Request) -> BoardThreadResponse:
    board_repo = get_board_repo(request)
    client_repo = get_client_repo(request)
    row = await board_repo.get_thread(thread_id)
    if row is None:
        raise _not_found()
    user = await get_current_user_from_request(request)
    if row.get("client_id") is not None:
        await _require_client_access(client_repo, row["client_id"], str(user.id))
    updated = await board_repo.patch_thread(thread_id, status=body.status, subject=body.subject)
    if updated is None:
        raise _not_found()
    return _to_thread_response(updated)


@router.get("/threads/{thread_id}/messages", response_model=BoardMessageListResponse)
@require_permission("board", "read")
async def list_board_messages(thread_id: str, request: Request) -> BoardMessageListResponse:
    board_repo = get_board_repo(request)
    client_repo = get_client_repo(request)
    row = await board_repo.get_thread(thread_id)
    if row is None:
        raise _not_found()
    user = await get_current_user_from_request(request)
    if row.get("client_id") is not None:
        await _require_client_access(client_repo, row["client_id"], str(user.id))
    messages = await board_repo.list_messages(thread_id) or []
    return BoardMessageListResponse(messages=[_to_message_response(m) for m in messages])


@router.post("/threads/{thread_id}/messages", response_model=BoardMessageResponse, status_code=201)
@require_permission("board", "write")
async def add_board_message(thread_id: str, body: BoardMessageCreateRequest, request: Request) -> BoardMessageResponse:
    board_repo = get_board_repo(request)
    client_repo = get_client_repo(request)
    row = await board_repo.get_thread(thread_id)
    if row is None:
        raise _not_found()
    user = await get_current_user_from_request(request)
    user_id = str(user.id)
    if row.get("client_id") is not None:
        await _require_client_access(client_repo, row["client_id"], user_id)
    # Author identity is never taken from the request body: a "momo" message only
    # ever comes from the draft workflow, and "owner" only from an actual admin.
    author_kind = "owner" if await _is_active_org_admin(user_id) else "client"
    message = await board_repo.add_message(thread_id, author_kind=author_kind, author_user_id=user_id, body=body.body)
    if message is None:
        raise _not_found()
    return _to_message_response(message)


async def _load_thread_for_actor(board_repo, client_repo, thread_id: str, request: Request) -> tuple[dict, str]:
    """Fetch *thread_id*, enforcing per-client access; returns ``(row, actor_user_id)``."""
    row = await board_repo.get_thread(thread_id)
    if row is None:
        raise _not_found()
    user = await get_current_user_from_request(request)
    user_id = str(user.id)
    if row.get("client_id") is not None:
        await _require_client_access(client_repo, row["client_id"], user_id)
    return row, user_id


@router.post("/threads/{thread_id}/draft", response_model=BoardThreadResponse)
@require_permission("board", "write")
async def draft_board_reply(thread_id: str, body: BoardDraftRequest, request: Request) -> BoardThreadResponse:
    """Momo drafts a reply: adds a ``momo``-authored message and moves the thread to ``drafted``."""
    board_repo = get_board_repo(request)
    client_repo = get_client_repo(request)
    row, user_id = await _load_thread_for_actor(board_repo, client_repo, thread_id, request)
    try:
        assert_can_draft(row["status"])
    except BoardTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await board_repo.add_message(thread_id, author_kind="momo", author_user_id=None, body=body.body)
    updated = await board_repo.patch_thread(thread_id, status=BoardThreadStatus.DRAFTED)
    if updated is None:
        raise _not_found()
    await record_audit_event(request, action="board.thread.drafted", outcome="success", actor_user_id=user_id, organization_id=resolve_organization_id(), target_type="board_thread", target_id=thread_id)
    return _to_thread_response(updated)


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
    return _to_thread_response(updated)


@router.post("/threads/{thread_id}/reply", response_model=BoardThreadResponse)
@require_permission("board", "write")
async def send_board_reply(thread_id: str, body: BoardReplyRequest, request: Request) -> BoardThreadResponse:
    """``replied`` needs its own explicit owner action, separate from ``approve``."""
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
    await board_repo.add_message(thread_id, author_kind="owner", author_user_id=user_id, body=body.body)
    updated = await board_repo.patch_thread(thread_id, status=BoardThreadStatus.REPLIED)
    if updated is None:
        raise _not_found()
    await record_audit_event(request, action="board.thread.replied", outcome="success", actor_user_id=user_id, organization_id=resolve_organization_id(), target_type="board_thread", target_id=thread_id)
    return _to_thread_response(updated)
