"""Client-safe projection of opt-in Board conversations. No external sends.

Draft messages are immutable; a versioned pending action publishes an exact
snapshot through the existing approvals inbox. Old Board threads stay internal.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.gateway.approval_adapters import register_adapter
from app.gateway.deps import get_current_user_from_request
from app.gateway.routers.clients import _is_active_org_admin
from deerflow.approvals import AdapterOutcome, InvalidPayloadError, register_action_type
from deerflow.persistence.approvals.model import PendingActionRow
from deerflow.persistence.board.model import BoardMessageRow, BoardPortalRow, BoardThreadRow
from deerflow.persistence.clients.model import ClientAssignmentRow, ClientRow
from deerflow.persistence.organizations.model import OrganizationMemberRow, OrganizationRow
from deerflow.runtime.user_context import get_effective_user_id, resolve_organization_id

router = APIRouter(prefix="/api/client-portal", tags=["client-portal"])
MAX_CHAT = "/workspace/agents/momobot-max/chats/new"


def _sf():
    from deerflow.persistence.engine import get_session_factory

    factory = get_session_factory()
    if factory is None:
        raise HTTPException(503, "Inbox requires persistent storage")
    return factory


def _hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def _missing():
    return HTTPException(404, "Conversation not found")


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Compose(Closed):
    client_id: str = Field(min_length=1, max_length=64)
    submission_key: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    subject: str = Field(min_length=1, max_length=255)
    body: str = Field(min_length=1, max_length=12000)


class Attachment(Closed):
    name: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9_. -]*\.(md|txt|csv)$")
    content: str = Field(max_length=20000)


class Draft(Closed):
    expected_revision: int = Field(ge=0)
    body: str = Field(min_length=1, max_length=12000)
    attachments: list[Attachment] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def unique_attachment_names(self) -> Draft:
        names = [attachment.name for attachment in self.attachments]
        if len(names) != len(set(names)):
            raise ValueError("Deliverable filenames must be unique")
        return self


class Publish(Closed):
    approval_id: str = Field(min_length=1, max_length=64)
    expected_revision: int = Field(ge=1)


class CustomerWorkspace(Closed):
    client_id: str = Field(min_length=1, max_length=64)
    user_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=256)


async def _identity(request):
    user = await get_current_user_from_request(request)
    org = resolve_organization_id()
    if not org:
        raise HTTPException(403, "Active workspace membership required")
    expected = request.headers.get("X-Portal-Workspace")
    if expected is not None and expected != org:
        raise HTTPException(409, "Workspace changed; reload the inbox")
    admin = await _is_active_org_admin(str(user.id))
    async with _sf()() as session:
        contact = (
            (
                await session.execute(
                    select(ClientAssignmentRow.client_id).where(
                        ClientAssignmentRow.organization_id == org,
                        ClientAssignmentRow.user_id == str(user.id),
                        ClientAssignmentRow.role == "client_contact",
                    )
                )
            )
            .scalars()
            .first()
        )
    # A normal member with a client-contact assignment is client-facing too.
    external = getattr(user, "system_role", None) == "client" or contact is not None
    return str(user.id), org, admin and not external, external


async def _client_ids(actor, org, admin):
    async with _sf()() as session:
        binding = await session.scalar(select(OrganizationRow.customer_client_id).where(OrganizationRow.id == org))
        if binding:
            # Read the canonical agency client; never clone it into a second roster.
            stmt = select(ClientRow.id, ClientRow.display_name).where(ClientRow.id == binding, ClientRow.status == "active")
            if not admin:
                stmt = stmt.join(ClientAssignmentRow, ClientAssignmentRow.client_id == ClientRow.id).where(ClientAssignmentRow.user_id == actor, ClientAssignmentRow.organization_id == org, ClientAssignmentRow.role == "client_contact")
            return {row.id: row.display_name for row in (await session.execute(stmt)).all()}
        stmt = select(ClientRow.id, ClientRow.display_name).where(ClientRow.organization_id == org, ClientRow.status == "active")
        if not admin:
            stmt = stmt.join(ClientAssignmentRow, ClientAssignmentRow.client_id == ClientRow.id).where(
                ClientAssignmentRow.user_id == actor,
                ClientAssignmentRow.organization_id == org,
            )
        return {row.id: row.display_name for row in (await session.execute(stmt)).all()}


async def _load(request, thread_id):
    actor, org, admin, external = await _identity(request)
    ids = await _client_ids(actor, org, admin)
    async with _sf()() as session:
        row = (
            await session.execute(
                select(BoardThreadRow, BoardPortalRow)
                .join(
                    BoardPortalRow,
                    BoardPortalRow.thread_id == BoardThreadRow.id,
                )
                .where(BoardPortalRow.thread_id == thread_id, BoardPortalRow.organization_id == org, BoardThreadRow.organization_id == org, BoardThreadRow.client_id.in_(ids))
            )
        ).first()
    if row is None:
        raise _missing()
    return row[0], row[1], admin, external


@router.post("/customer-workspaces", status_code=201)
async def provision_customer_workspace(body: CustomerWorkspace, request: Request):
    """Fresh storage only. Reuse workspace creation and the canonical client row."""
    from app.gateway.routers.workspaces import WorkspaceCreateRequest, create_workspace
    from deerflow.persistence.user.model import UserRow

    actor, org, admin, external = await _identity(request)
    user = await get_current_user_from_request(request)
    if not admin or getattr(user, "system_role", None) != "admin":
        raise HTTPException(403, "Global administrator and agency owner/admin required")
    async with _sf()() as session:
        canonical = await session.get(ClientRow, body.client_id)
        customer = await session.get(UserRow, body.user_id)
        if canonical is None or canonical.organization_id != org or canonical.status != "active":
            raise _missing()
        if customer is None or customer.system_role != "client" or customer.disabled_at is not None:
            raise HTTPException(422, "Choose an existing active client account")
        existing = await session.scalar(select(ClientAssignmentRow.client_id).where(ClientAssignmentRow.user_id == body.user_id).limit(1))
        shared = await session.scalar(
            select(OrganizationMemberRow.organization_id)
            .join(OrganizationRow, OrganizationRow.id == OrganizationMemberRow.organization_id)
            .where(OrganizationMemberRow.user_id == body.user_id, OrganizationMemberRow.status == "active", OrganizationRow.storage_user_id.is_not(None))
            .limit(1)
        )
        if existing or shared:
            raise HTTPException(409, "Client account is already assigned; review its existing workspace")
    # Existing service allocates a new random storage principal and organization.
    # No caller can bind an old agency bucket. If binding fails, this empty
    # admin-only workspace remains inaccessible to the customer.
    created = await create_workspace(WorkspaceCreateRequest(name=body.name), request)
    now = datetime.now(UTC)
    async with _sf()() as session, session.begin():
        target = await session.get(OrganizationRow, created.id)
        if target is None or target.customer_client_id is not None or target.storage_user_id is None:
            raise HTTPException(409, "Fresh workspace validation failed")
        target.customer_client_id = body.client_id
        session.add(OrganizationMemberRow(organization_id=created.id, user_id=body.user_id, role="member", status="active", created_at=now, updated_at=now))
        session.add(ClientAssignmentRow(client_id=body.client_id, user_id=body.user_id, organization_id=created.id, role="client_contact", created_at=now, updated_at=now))
    return {"workspace_id": created.id, "client_id": body.client_id, "user_id": body.user_id, "delivery": "portal"}


def _message(message):
    return {
        "id": message.id,
        "author": "MomoBot" if message.author_kind == "owner" else "You",
        "body": message.body,
        "created_at": message.created_at.isoformat(),
        "attachments": [{"name": a["name"], "sha256": a["sha256"]} for a in message.attachments or []],
    }


async def _summary(thread, portal, staff, request):
    state = "published" if portal.published_id else "needs_approval" if portal.approval_id else "pending"
    out = {"id": thread.id, "client_id": thread.client_id, "subject": thread.subject, "state": state, "updated_at": thread.updated_at.isoformat(), "revision": portal.revision, "publish_receipt": portal.published_id, "momo_href": MAX_CHAT}
    if staff:
        out.update(approval_id=portal.approval_id, work_chat_id=portal.work_chat_id, work_run_id=portal.work_run_id)
    if portal.work_run_id and not portal.approval_id and not portal.published_id:
        from app.gateway.deps import get_run_manager

        record = await get_run_manager(request).get(portal.work_run_id, user_id=get_effective_user_id())
        out["work_status"] = str(record.status) if record else "unavailable"
        out["state"] = "running" if record and str(record.status) in {"pending", "running"} else "pending"
    return out


@router.get("/clients")
async def portal_clients(request: Request):
    actor, org, admin, external = await _identity(request)
    ids = await _client_ids(actor, org, admin)
    return {"workspace_id": org, "clients": [{"id": key, "name": name} for key, name in ids.items()], "can_review": admin, "can_draft": not external}


@router.get("/threads")
async def list_threads(
    request: Request, q: str = Query(default="", max_length=200), state: Literal["all", "pending", "needs_approval", "published"] = "all", limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0, le=10000)
):
    actor, org, admin, external = await _identity(request)
    ids = await _client_ids(actor, org, admin)
    stmt = select(BoardThreadRow, BoardPortalRow).join(BoardPortalRow, BoardPortalRow.thread_id == BoardThreadRow.id).where(BoardThreadRow.organization_id == org, BoardPortalRow.organization_id == org, BoardThreadRow.client_id.in_(ids))
    if q.strip():
        # Literal substring, not caller-controlled SQL wildcard syntax.
        stmt = stmt.where(BoardThreadRow.subject.contains(q.strip(), autoescape=True))
    if state == "published":
        stmt = stmt.where(BoardPortalRow.published_id.is_not(None))
    elif state == "needs_approval":
        stmt = stmt.where(BoardPortalRow.approval_id.is_not(None), BoardPortalRow.published_id.is_(None))
    elif state == "pending":
        stmt = stmt.where(BoardPortalRow.approval_id.is_(None), BoardPortalRow.published_id.is_(None))
    async with _sf()() as session:
        rows = (await session.execute(stmt.order_by(BoardThreadRow.updated_at.desc(), BoardThreadRow.id).offset(offset).limit(limit + 1))).all()
    return {"threads": [await _summary(t, p, not external, request) for t, p in rows[:limit]], "has_more": len(rows) > limit}


@router.post("/threads")
async def compose(body: Compose, request: Request):
    actor, org, admin, external = await _identity(request)
    if body.client_id not in await _client_ids(actor, org, admin):
        raise _missing()
    fingerprint = _hash(body.model_dump(exclude={"submission_key"}))
    thread_id = uuid.uuid4().hex
    now = datetime.now(UTC)
    async with _sf()() as session:
        try:
            async with session.begin():
                session.add(BoardThreadRow(id=thread_id, organization_id=org, client_id=body.client_id, kind="ticket", status="new", subject=body.subject, created_by_user_id=actor, created_at=now, updated_at=now))
                session.add(BoardPortalRow(thread_id=thread_id, organization_id=org, actor_id=actor, submission_key=body.submission_key, submission_hash=fingerprint, revision=0))
                session.add(BoardMessageRow(id=uuid.uuid4().hex, thread_id=thread_id, author_kind="client", author_user_id=actor, body=body.body, visibility="published", attachments=[], created_at=now))
        except IntegrityError:
            await session.rollback()
            existing = (await session.execute(select(BoardPortalRow).where(BoardPortalRow.organization_id == org, BoardPortalRow.actor_id == actor, BoardPortalRow.submission_key == body.submission_key))).scalar_one_or_none()
            if existing is None:
                raise
            if existing.submission_hash != fingerprint:
                raise HTTPException(409, "Submission key already used for a different request") from None
            thread_id = existing.thread_id
    return await detail(thread_id, request)


@router.get("/threads/{thread_id}")
async def detail(thread_id: str, request: Request):
    thread, portal, admin, external = await _load(request, thread_id)
    async with _sf()() as session:
        stmt = select(BoardMessageRow).where(BoardMessageRow.thread_id == thread_id)
        if external:
            stmt = stmt.where(BoardMessageRow.visibility == "published")
        messages = (await session.execute(stmt.order_by(BoardMessageRow.created_at, BoardMessageRow.id))).scalars().all()
    out = await _summary(thread, portal, not external, request)
    out.update(messages=[_message(m) for m in messages], can_review=admin, can_draft=not external)
    if not external:
        draft = next((m for m in messages if m.id == portal.draft_id), None)
        out["draft"] = {"body": draft.body, "attachments": draft.attachments or []} if draft else None
    return out


def _snapshot(thread_id, revision, draft):
    return {"portal_thread_id": thread_id, "revision": revision, "draft_id": draft.id, "body": draft.body, "attachments": draft.attachments or []}


@router.post("/threads/{thread_id}/draft")
async def save_draft(thread_id: str, body: Draft, request: Request):
    thread, portal, admin, external = await _load(request, thread_id)
    if external:
        raise HTTPException(403, "Staff access required")
    attachments = [{**a.model_dump(), "sha256": hashlib.sha256(a.content.encode()).hexdigest()} for a in body.attachments]
    if len(json.dumps(attachments).encode()) + len(body.body.encode()) > 18000:
        raise HTTPException(422, "Draft and attachments must fit within 18000 bytes")
    now = datetime.now(UTC)
    draft = BoardMessageRow(id=uuid.uuid4().hex, thread_id=thread_id, author_kind="momo", body=body.body, visibility="internal", attachments=attachments, created_at=now)
    revision = body.expected_revision + 1
    approval_id = uuid.uuid4().hex
    payload = _snapshot(thread_id, revision, draft)
    async with _sf()() as session, session.begin():
        result = await session.execute(
            update(BoardPortalRow)
            .where(BoardPortalRow.thread_id == thread_id, BoardPortalRow.organization_id == portal.organization_id, BoardPortalRow.revision == body.expected_revision, BoardPortalRow.published_id.is_(None))
            .values(revision=revision, draft_id=draft.id, approval_id=approval_id)
        )
        if result.rowcount != 1:
            raise HTTPException(409, "Conversation changed; reload before saving")
        session.add(draft)
        session.add(
            PendingActionRow(
                id=approval_id,
                user_id=get_effective_user_id(),
                organization_id=portal.organization_id,
                action_type="portal_publish",
                title=f"Publish: {thread.subject}"[:255],
                target=thread_id,
                payload=payload,
                original_payload=payload,
                status="pending",
                thread_id=portal.work_chat_id,
                run_id=portal.work_run_id,
                agent_name="MomoBot1.1",
                created_at=now,
                updated_at=now,
            )
        )
        if portal.approval_id:
            await session.execute(
                update(PendingActionRow)
                .where(PendingActionRow.id == portal.approval_id, PendingActionRow.organization_id == portal.organization_id, PendingActionRow.status == "pending")
                .values(status="rejected", error="Superseded by a new draft", updated_at=now)
            )
        await session.execute(update(BoardThreadRow).where(BoardThreadRow.id == thread_id).values(status="drafted", updated_at=now))
    return await detail(thread_id, request)


def _validate(target, payload):
    if target != payload.get("portal_thread_id") or not isinstance(payload.get("revision"), int) or not payload.get("draft_id"):
        raise InvalidPayloadError("Invalid portal approval snapshot")


class PortalPublishAdapter:
    async def execute(self, action):
        org = resolve_organization_id()
        if not org or action.get("organization_id") != org:
            return AdapterOutcome("failed", error="Workspace no longer available")
        # Generic approvals edits cannot replace the original immutable snapshot.
        if action["payload"] != action["original_payload"]:
            return AdapterOutcome("failed", error="Edit the inbox draft and approve its new version")
        payload = action["original_payload"]
        receipt = hashlib.sha256(f"portal:{action['id']}".encode()).hexdigest()
        async with _sf()() as session, session.begin():
            portal = await session.get(BoardPortalRow, action["target"])
            if portal is None or portal.organization_id != org:
                return AdapterOutcome("failed", error="Conversation unavailable")
            if portal.published_id == receipt:
                return AdapterOutcome("executed", {"portal_receipt": receipt, "delivery": "portal"})
            draft = await session.get(BoardMessageRow, payload["draft_id"])
            if draft is None or draft.thread_id != portal.thread_id or _snapshot(portal.thread_id, portal.revision, draft) != payload:
                return AdapterOutcome("failed", error="Draft changed; approve its current version")
            result = await session.execute(
                update(BoardPortalRow)
                .where(BoardPortalRow.thread_id == portal.thread_id, BoardPortalRow.organization_id == org, BoardPortalRow.revision == payload["revision"], BoardPortalRow.approval_id == action["id"], BoardPortalRow.published_id.is_(None))
                .values(published_id=receipt)
            )
            if result.rowcount != 1:
                existing = await session.scalar(select(BoardPortalRow.published_id).where(BoardPortalRow.thread_id == portal.thread_id))
                if existing == receipt:
                    return AdapterOutcome("executed", {"portal_receipt": receipt, "delivery": "portal"})
                return AdapterOutcome("failed", error="Draft changed or publication already in progress")
            now = datetime.now(UTC)
            session.add(BoardMessageRow(id=receipt, thread_id=portal.thread_id, author_kind="owner", author_user_id=action.get("decided_by"), body=draft.body, visibility="published", attachments=draft.attachments, created_at=now))
            await session.execute(update(BoardThreadRow).where(BoardThreadRow.id == portal.thread_id, BoardThreadRow.organization_id == org).values(status="replied", updated_at=now))
        return AdapterOutcome("executed", {"portal_receipt": receipt, "delivery": "portal"})


register_action_type("portal_publish", _validate)
register_adapter("portal_publish", PortalPublishAdapter())


@router.post("/threads/{thread_id}/publish")
async def publish(thread_id: str, body: Publish, request: Request):
    thread, portal, admin, external = await _load(request, thread_id)
    if not admin:
        raise HTTPException(403, "An organization owner or admin must approve publication")
    if portal.approval_id != body.approval_id or portal.revision != body.expected_revision:
        raise HTTPException(409, "Draft changed; review the current version")
    if portal.published_id:
        return await detail(thread_id, request)
    from app.gateway.deps import get_pending_action_repo
    from app.gateway.routers.approvals import approve_action

    repo = get_pending_action_repo(request)
    approved = await repo.get(body.approval_id)
    if approved and approved["status"] == "approved":
        # Safe recovery after a worker stops between approval and publication.
        # Only this DB-only adapter is resumable; no external delivery is retried.
        outcome = await PortalPublishAdapter().execute(approved)
        await repo.record_outcome(body.approval_id, status=outcome.status, result=outcome.detail, error=outcome.error)
    else:
        try:
            await approve_action(action_id=body.approval_id, request=request)
        except HTTPException as exc:
            if exc.status_code != 409:
                raise
            result = await detail(thread_id, request)
            if result["publish_receipt"]:
                return result
            raise
    result = await detail(thread_id, request)
    if not result["publish_receipt"]:
        raise HTTPException(409, "Publication did not complete; inspect the approval result")
    return result


@router.get("/threads/{thread_id}/messages/{message_id}/attachments/{name}")
async def attachment(thread_id: str, message_id: str, name: str, request: Request):
    _, _, _, external = await _load(request, thread_id)
    async with _sf()() as session:
        message = await session.get(BoardMessageRow, message_id)
    if message is None or message.thread_id != thread_id or (external and message.visibility != "published"):
        raise _missing()
    item = next((a for a in message.attachments or [] if a["name"] == name), None)
    if item is None:
        raise _missing()
    return Response(item["content"], media_type="text/plain", headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store", "X-Content-SHA256": item["sha256"]})


async def _chat(thread_id: str, request: Request, *, work: bool):
    thread, portal, admin, external = await _load(request, thread_id)
    actor = str((await get_current_user_from_request(request)).id)
    if (work and external) or (not work and actor != portal.actor_id):
        raise _missing()
    if not work:
        from app.gateway.client_workspace import require_client_workspace

        await require_client_workspace(await get_current_user_from_request(request))
    from app.gateway.deps import get_thread_store

    store = get_thread_store(request)
    column = "work_chat_id" if work else "client_chat_id"
    chat_id = f"portal-{'work' if work else 'client'}-{thread_id}"
    if await store.get(chat_id) is None:
        try:
            await store.create(chat_id, assistant_id="momobot-max", display_name=thread.subject)
        except IntegrityError:
            if await store.get(chat_id) is None:
                raise
    async with _sf()() as session, session.begin():
        await session.execute(update(BoardPortalRow).where(BoardPortalRow.thread_id == thread_id, BoardPortalRow.organization_id == portal.organization_id).values(**{column: chat_id}))
    return {"chat_id": chat_id, "href": f"/workspace/agents/momobot-max/chats/{chat_id}"}


@router.post("/threads/{thread_id}/chat")
async def client_chat(thread_id: str, request: Request):
    return await _chat(thread_id, request, work=False)


@router.post("/threads/{thread_id}/work")
async def start_work(thread_id: str, request: Request):
    chat = await _chat(thread_id, request, work=True)
    thread, portal, _, external = await _load(request, thread_id)
    if portal.published_id or portal.approval_id:
        raise HTTPException(409, "A draft or published response already exists")
    from app.gateway.routers.thread_runs import create_run
    from app.gateway.run_models import RunCreateRequest

    async with _sf()() as session:
        first = (await session.execute(select(BoardMessageRow).where(BoardMessageRow.thread_id == thread_id, BoardMessageRow.author_kind == "client").order_by(BoardMessageRow.created_at, BoardMessageRow.id))).scalars().first()
    body = RunCreateRequest(
        assistant_id="momobot-max",
        input={
            "messages": [
                {
                    "role": "user",
                    "content": (
                        f"Client request: {thread.subject}\n{first.body if first else ''}\n"
                        "Produce a source-backed reply draft and useful deliverable for staff review. "
                        "Never send or publish. Save outputs and identify evidence; no invented metrics."
                    ),
                }
            ]
        },
    )
    record = await create_run(thread_id=chat["chat_id"], body=body, request=request, idempotency_key=f"portal-work-{thread_id}")
    async with _sf()() as session, session.begin():
        await session.execute(update(BoardPortalRow).where(BoardPortalRow.thread_id == thread_id, BoardPortalRow.organization_id == portal.organization_id).values(work_run_id=record.run_id))
    return {**chat, "run_id": record.run_id, "status": record.status}
