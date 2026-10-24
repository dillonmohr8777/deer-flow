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
from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator
from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError

from app.gateway.approval_adapters import register_adapter
from app.gateway.client_boundary import CLIENT_ROLE
from app.gateway.deps import get_current_user_from_request
from app.gateway.invitation_policy import fresh_customer_assignments, validate_customer_workspace
from app.gateway.routers.clients import _is_active_org_admin
from deerflow.approvals import AdapterOutcome, InvalidPayloadError, register_action_type
from deerflow.persistence.approvals.model import PendingActionRow
from deerflow.persistence.board.model import BoardMessageRow, BoardPortalRow, BoardThreadRow
from deerflow.persistence.clients.model import ClientAssignmentRow, ClientRow
from deerflow.persistence.organizations.model import OrganizationMemberRow, OrganizationRow
from deerflow.runtime.user_context import get_effective_user_id, resolve_organization_id
from deerflow.utils.thread_id import ThreadId

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


class CustomerWorkspaceInvitation(Closed):
    client_id: str = Field(min_length=1, max_length=64)
    email: EmailStr
    name: str = Field(min_length=1, max_length=256)


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
    external = getattr(user, "system_role", None) == CLIENT_ROLE or contact is not None
    return str(user.id), org, admin and not external, external


async def _client_ids(actor, org, admin, external=True):
    async with _sf()() as session:
        binding = await session.scalar(select(OrganizationRow.customer_client_id).where(OrganizationRow.id == org))
        if binding:
            # Read the canonical agency client; never clone it into a second roster.
            stmt = select(ClientRow.id, ClientRow.display_name).where(ClientRow.id == binding, ClientRow.status == "active")
            if not admin:
                assigned = and_(ClientAssignmentRow.organization_id == org, ClientAssignmentRow.role == "client_contact")
                if not external:
                    active_member = (
                        select(OrganizationMemberRow.user_id)
                        .where(OrganizationMemberRow.organization_id == org, OrganizationMemberRow.user_id == actor, OrganizationMemberRow.status == "active", OrganizationMemberRow.role.in_(("owner", "admin", "member")))
                        .exists()
                    )
                    assigned = or_(assigned, and_(ClientAssignmentRow.organization_id == ClientRow.organization_id, ClientAssignmentRow.role == "account_manager", ClientRow.organization_id != org, active_member))
                stmt = stmt.join(ClientAssignmentRow, ClientAssignmentRow.client_id == ClientRow.id).where(ClientAssignmentRow.user_id == actor, assigned)
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
    ids = await _client_ids(actor, org, admin, external)
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


async def _customer_admin(request):
    from app.gateway.routers.workspaces import _session_actor

    actor, org, admin, external = await _identity(request)
    user = _session_actor(request)
    if not admin or getattr(user, "system_role", None) != "admin":
        raise HTTPException(403, "Global administrator and agency owner/admin required")
    return actor, org


async def _customer_client(session, *, client_id, org, actor):
    from deerflow.persistence.organizations.invitation_policy import active_shared_workspace_member

    # The first statement is a write: FOR UPDATE alone is ignored on SQLite.
    # Every supported provisioner takes this canonical row lock before looking for a binding.
    locked = await session.execute(update(ClientRow).where(ClientRow.id == client_id, ClientRow.organization_id == org, ClientRow.status == "active").values(updated_at=ClientRow.updated_at))
    if locked.rowcount != 1:
        raise _missing()
    agency, member = await active_shared_workspace_member(session, org, actor)
    if agency is None or member is None or agency.customer_client_id is not None:
        raise HTTPException(403, "Active agency owner/admin required")
    return await session.get(ClientRow, client_id)


async def _bound_customer_workspace(session, *, canonical, actor):
    targets = (await session.scalars(select(OrganizationRow).where(OrganizationRow.customer_client_id == canonical.id))).all()
    if not targets:
        return None
    if len(targets) != 1:
        raise HTTPException(409, "Client already has conflicting customer workspaces; review its binding")
    target = targets[0]
    await validate_customer_workspace(session, organization=target, actor_id=actor, canonical=canonical)
    return target


@router.post("/customer-workspaces", status_code=201)
async def provision_customer_workspace(body: CustomerWorkspace, request: Request):
    """Fresh existing accounts keep the no-shared-membership migration guard."""
    from app.gateway.routers.invitations import _locked_invitation_user
    from app.gateway.routers.workspaces import _create_workspace_rows

    actor, org = await _customer_admin(request)
    now = datetime.now(UTC)
    async with _sf()() as session, session.begin():
        canonical = await _customer_client(session, client_id=body.client_id, org=org, actor=actor)
        customer = await _locked_invitation_user(session, body.user_id)
        if customer is None or customer.system_role != CLIENT_ROLE or customer.disabled_at is not None:
            raise HTTPException(422, "Choose an existing active client account")
        await fresh_customer_assignments(session, customer)
        if await _bound_customer_workspace(session, canonical=canonical, actor=actor) is not None:
            raise HTTPException(409, "Client already has a customer workspace; invite its contact there")
        target = await _create_workspace_rows(session, actor_id=actor, name=body.name, now=now)
        target.customer_client_id = body.client_id
        await validate_customer_workspace(session, organization=target, actor_id=actor, canonical=canonical)
        session.add(OrganizationMemberRow(organization_id=target.id, user_id=body.user_id, role="client", status="active", created_at=now, updated_at=now))
        session.add(ClientAssignmentRow(client_id=body.client_id, user_id=body.user_id, organization_id=target.id, role="client_contact", created_at=now, updated_at=now))
    return {"workspace_id": target.id, "client_id": body.client_id, "user_id": body.user_id, "delivery": "portal"}


@router.post("/customer-workspaces/migrations", status_code=201)
async def migrate_customer_workspace(body: CustomerWorkspace, request: Request):
    """Explicit admin migration of one agency contact; never move shared history."""
    from app.gateway.routers.invitations import _locked_invitation_user, record_audit_event
    from app.gateway.routers.workspaces import _create_workspace_rows

    actor, org = await _customer_admin(request)
    now = datetime.now(UTC)
    async with _sf()() as session, session.begin():
        canonical = await _customer_client(session, client_id=body.client_id, org=org, actor=actor)
        customer = await _locked_invitation_user(session, body.user_id)
        if customer is None or customer.system_role != CLIENT_ROLE or customer.disabled_at is not None:
            raise HTTPException(422, "Choose an existing active client account")
        assignments = (await session.scalars(select(ClientAssignmentRow).where(ClientAssignmentRow.user_id == customer.id))).all()
        memberships = (
            await session.scalars(
                select(OrganizationMemberRow)
                .join(OrganizationRow, OrganizationRow.id == OrganizationMemberRow.organization_id)
                .where(OrganizationMemberRow.user_id == customer.id, OrganizationMemberRow.status == "active", OrganizationRow.storage_user_id.is_not(None))
            )
        ).all()
        if (
            len(assignments) != 1
            or assignments[0].client_id != canonical.id
            or assignments[0].organization_id != org
            or assignments[0].role != "client_contact"
            or len(memberships) != 1
            or memberships[0].organization_id != org
            or memberships[0].role != "client"
        ):
            raise HTTPException(409, "Migration requires one matching agency client contact and no other shared membership")
        target = await _bound_customer_workspace(session, canonical=canonical, actor=actor)
        if target is None:
            target = await _create_workspace_rows(session, actor_id=actor, name=body.name, now=now)
            target.customer_client_id = canonical.id
            await validate_customer_workspace(session, organization=target, actor_id=actor, canonical=canonical)
        # Preserve private membership/history; shared storage has no per-person provenance.
        memberships[0].status = "inactive"
        memberships[0].updated_at = now
        assignments[0].organization_id = target.id
        assignments[0].updated_at = now
        member = await session.get(OrganizationMemberRow, {"organization_id": target.id, "user_id": customer.id})
        if member is None:
            session.add(OrganizationMemberRow(organization_id=target.id, user_id=customer.id, role="client", status="active", created_at=now, updated_at=now))
        else:
            member.role, member.status, member.updated_at = "client", "active", now
    await record_audit_event(
        request, action="customer_workspace.migrated", outcome="success", actor_user_id=actor, organization_id=target.id, target_type="user", target_id=body.user_id, details={"source_workspace_id": org, "client_id": body.client_id}
    )
    return {"workspace_id": target.id, "client_id": body.client_id, "user_id": body.user_id, "delivery": "portal"}


@router.post("/customer-workspaces/invitations", status_code=201)
async def invite_customer_workspace(body: CustomerWorkspaceInvitation, request: Request, response: Response):
    """Create/bind first, then issue the existing private single-use invitation."""
    from app.gateway.routers import invitations
    from app.gateway.routers.workspaces import _create_workspace_rows

    invitations._no_store(response)
    invitations._refuse_if_frozen()
    if not invitations.role_has_policy("client"):
        raise HTTPException(409, "Role 'client' is not defined under authorization.provider.config.roles; add it before inviting clients")
    actor, org = await _customer_admin(request)
    now = datetime.now(UTC)
    email = str(body.email).lower()
    async with _sf()() as session, session.begin():
        canonical = await _customer_client(session, client_id=body.client_id, org=org, actor=actor)
        target = await _bound_customer_workspace(session, canonical=canonical, actor=actor)
        customer = await invitations._find_user_by_email(session, email)
        if customer is not None:
            customer = await invitations._locked_invitation_user(session, customer.id)
            await fresh_customer_assignments(session, customer, target_id=target.id if target else None, client_id=body.client_id)
        if target is None:
            target = await _create_workspace_rows(session, actor_id=actor, name=body.name, now=now)
            target.customer_client_id = body.client_id
            await validate_customer_workspace(session, organization=target, actor_id=actor, canonical=canonical)
        # Only pending client links for this workspace/email are rotated. A retry returns a fresh token.
        await session.execute(
            update(invitations.InvitationRow)
            .where(invitations.InvitationRow.organization_id == target.id, invitations.InvitationRow.email == email, invitations.InvitationRow.role == "client", invitations.InvitationRow.consumed_at.is_(None))
            .values(consumed_at=now, updated_at=now)
        )
        created = invitations._create_invitation_row(session, organization=target, email=email, role="client", actor_id=actor, now=now)
    await invitations.record_audit_event(
        request, action="invitation.created", outcome="success", actor_user_id=actor, organization_id=target.id, target_type="invitation", target_id=created.id, details={"email": email, "role": "client", "client_id": body.client_id}
    )
    return {"workspace_id": target.id, "client_id": body.client_id, **created.model_dump()}


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
    ids = await _client_ids(actor, org, admin, external)
    return {"workspace_id": org, "clients": [{"id": key, "name": name} for key, name in ids.items()], "can_review": admin, "can_draft": not external}


@router.get("/threads")
async def list_threads(
    request: Request, q: str = Query(default="", max_length=200), state: Literal["all", "pending", "needs_approval", "published"] = "all", limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0, le=10000)
):
    actor, org, admin, external = await _identity(request)
    ids = await _client_ids(actor, org, admin, external)
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
    # Compose writes client-visible content immediately; keep its original admission.
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
async def detail(thread_id: ThreadId, request: Request):
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
async def save_draft(thread_id: ThreadId, body: Draft, request: Request):
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
async def publish(thread_id: ThreadId, body: Publish, request: Request):
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
async def attachment(thread_id: ThreadId, message_id: str, name: str, request: Request):
    _, _, _, external = await _load(request, thread_id)
    async with _sf()() as session:
        message = await session.get(BoardMessageRow, message_id)
    if message is None or message.thread_id != thread_id or (external and message.visibility != "published"):
        raise _missing()
    item = next((a for a in message.attachments or [] if a["name"] == name), None)
    if item is None:
        raise _missing()
    return Response(item["content"], media_type="text/plain", headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store", "X-Content-SHA256": item["sha256"]})


async def _chat(thread_id: ThreadId, request: Request, *, work: bool):
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
    # The chat id is random and bound to the portal row once (compare-and-set),
    # never derived from thread_id: a predictable id could be pre-created by
    # another account and then reused, putting staff work in a client's thread.
    chat_id = getattr(portal, column)
    if chat_id is None:
        candidate = f"portal-{'work' if work else 'client'}-{uuid.uuid4().hex}"
        await store.create(candidate, assistant_id="momobot-max", display_name=thread.subject)
        async with _sf()() as session, session.begin():
            bound = await session.execute(
                update(BoardPortalRow).where(BoardPortalRow.thread_id == thread_id, BoardPortalRow.organization_id == portal.organization_id, getattr(BoardPortalRow, column).is_(None)).values(**{column: candidate})
            )
        if bound.rowcount == 1:
            chat_id = candidate
        else:  # a concurrent request bound its own chat first; use that one
            _, portal, _, _ = await _load(request, thread_id)
            chat_id = getattr(portal, column)
    if chat_id is None or await store.get(chat_id) is None:
        raise _missing()
    return {"chat_id": chat_id, "href": f"/workspace/agents/momobot-max/chats/{chat_id}"}


@router.post("/threads/{thread_id}/chat")
async def client_chat(thread_id: ThreadId, request: Request):
    return await _chat(thread_id, request, work=False)


@router.post("/threads/{thread_id}/work")
async def start_work(thread_id: ThreadId, request: Request):
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
                        "Match the client's requested scope and length. Treat supplied facts as drafting inputs and "
                        "mark missing details as missing; do not invent facts or withhold usable copy for nonessential "
                        "details. Put the requested deliverable first, then a brief missing-information checklist only "
                        "if needed. Research external sources only when the request calls for it or when you introduce "
                        "a material factual, legal, or compliance claim. Do not expand routine drafting into an "
                        "unsolicited memo or add approval or confirmation steps beyond the existing owner/admin "
                        "publication review. Produce an INTERNAL DRAFT reply for staff review. "
                        "Never send or publish. Assigned account managers may work, edit, and save drafts; "
                        "assignment alone grants no approval or publication authority. Publication review "
                        "requires an authorized workspace owner/admin. Support legal/compliance claims with "
                        "current authoritative sources; never infer a CAN-SPAM exemption from a professional "
                        "relationship or absence of an offer. Leave unresolved classifications/requirements "
                        "for qualified human review. Save outputs and identify evidence; no invented metrics. "
                        "This guidance does not verify facts or grant sender authority."
                    ),
                }
            ]
        },
    )
    record = await create_run(thread_id=chat["chat_id"], body=body, request=request, idempotency_key=f"portal-work-{thread_id}")
    async with _sf()() as session, session.begin():
        await session.execute(update(BoardPortalRow).where(BoardPortalRow.thread_id == thread_id, BoardPortalRow.organization_id == portal.organization_id).values(work_run_id=record.run_id))
    return {**chat, "run_id": record.run_id, "status": record.status}
