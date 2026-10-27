"""Recorded internal planning on an existing portal request; no execution."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import HTTPException
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import aliased

from app.gateway.client_boundary import CLIENT_ROLE
from deerflow.persistence.board.model import BoardPortalRow, BoardThreadRow
from deerflow.persistence.clients.model import ClientAssignmentRow, ClientRow
from deerflow.persistence.organizations.model import OrganizationMemberRow, OrganizationRow
from deerflow.persistence.user.model import UserRow

RecordId = Annotated[str, Field(min_length=1, max_length=64)]
MAX_PLAN_BYTES = 8000
DEFAULT_PARTICIPANT_LIMIT = 50
MAX_PARTICIPANT_LIMIT = 100
MAX_PARTICIPANT_CURSOR = 512


@dataclass(frozen=True)
class BoundWorkPlanScope:
    client_id: str
    chat_id: str
    storage_user_id: str
    project_id: str | None


class EvidenceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["source", "delivery"]
    reference: str = Field(min_length=1, max_length=512)

    @field_validator("reference")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Evidence references must not be blank")
        return value


class InternalWorkPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: str = Field(min_length=1, max_length=2000)
    assignee_user_id: RecordId | None = None
    due_at: AwareDatetime | None = None
    dependency_thread_ids: list[RecordId] = Field(default_factory=list, max_length=10)
    verifier_user_id: RecordId | None = None
    status: Literal["planned", "in_progress", "blocked", "reported_complete"] = "planned"
    next_action: str = Field(min_length=1, max_length=2000)
    evidence_refs: list[EvidenceReference] = Field(default_factory=list, max_length=10)

    @field_validator("outcome", "next_action")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Planning text must not be blank")
        return value

    @field_validator("due_at")
    @classmethod
    def utc_due_date(cls, value):
        return value.astimezone(UTC) if value is not None else None

    @model_validator(mode="after")
    def bounded_dependencies_and_completion(self):
        if len(self.dependency_thread_ids) != len(set(self.dependency_thread_ids)):
            raise ValueError("Dependency references must be unique")
        if self.status == "reported_complete" and not self.evidence_refs:
            raise ValueError("Reported completion requires a recorded evidence reference")
        return self


class WorkPlanUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(strict=True, ge=0, le=2147483646)
    plan: InternalWorkPlan


def _factory():
    from deerflow.persistence.engine import get_session_factory

    factory = get_session_factory()
    if factory is None:
        raise HTTPException(503, "Internal work planning requires persistent storage")
    return factory


async def _scoped(session, *, actor_id, organization_id, thread_id, scope: BoundWorkPlanScope | None = None):
    from app.gateway.client_context import _staff_client

    pair = (
        await session.execute(
            select(BoardThreadRow, BoardPortalRow)
            .join(BoardPortalRow, BoardPortalRow.thread_id == BoardThreadRow.id)
            .where(BoardThreadRow.id == thread_id, BoardThreadRow.organization_id == organization_id, BoardPortalRow.organization_id == organization_id)
        )
    ).first()
    if pair is None:
        raise HTTPException(404, "Internal work plan not found")
    await _staff_client(session, actor_id=actor_id, organization_id=organization_id, client_id=pair[0].client_id)
    if scope is not None:
        from deerflow.persistence.thread_meta.model import ThreadMetaRow
        from deerflow.persistence.user.model import UserRow

        thread, portal = pair
        metadata = await session.get(ThreadMetaRow, scope.chat_id)
        if await session.scalar(select(UserRow.system_role).where(UserRow.id == actor_id)) not in {"user", "exec", "admin"}:
            raise HTTPException(404, "Bound internal work plan not found")
        if (
            thread.client_id != scope.client_id
            or portal.work_chat_id != scope.chat_id
            or metadata is None
            or metadata.organization_id != organization_id
            or metadata.user_id != scope.storage_user_id
            or metadata.client_actor_id is not None
            or metadata.project_id != scope.project_id
        ):
            raise HTTPException(404, "Bound internal work plan not found")
        # Reject ambiguous/rebound chats exactly as portal-work admission does.
        bindings = list(await session.scalars(select(BoardPortalRow.thread_id).where(BoardPortalRow.work_chat_id == scope.chat_id).limit(2)))
        if bindings != [thread_id]:
            raise HTTPException(404, "Bound internal work plan not found")
        if scope.project_id is not None:
            from app.gateway.client_context import _staff_project

            await _staff_project(session, actor_id=actor_id, organization_id=organization_id, client_id=scope.client_id, project_id=scope.project_id, storage_user_id=scope.storage_user_id)
    return pair


def _participant_scope(actor_id, organization_id, client_id, thread_id):
    value = json.dumps([actor_id, organization_id, client_id, thread_id], separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _encode_participant_cursor(after, *, scope):
    value = json.dumps({"v": 1, "scope": scope, "after": after}, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode_participant_cursor(cursor, *, scope):
    def invalid():
        raise HTTPException(422, "Invalid work-plan participant cursor")

    if not isinstance(cursor, str) or len(cursor) > MAX_PARTICIPANT_CURSOR or re.fullmatch(r"[A-Za-z0-9_-]{1,512}", cursor) is None:
        invalid()
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        invalid()
    if (
        not isinstance(payload, dict)
        or set(payload) != {"v", "scope", "after"}
        or type(payload["v"]) is not int
        or payload["v"] != 1
        or payload["scope"] != scope
        or not isinstance(payload["after"], str)
        or not payload["after"]
        or len(payload["after"]) > 64
        or _encode_participant_cursor(payload["after"], scope=scope) != cursor
    ):
        invalid()
    return payload["after"]


def _eligible_participant_query(*, organization_id, client_id):
    workspace = aliased(OrganizationRow)
    agency = aliased(OrganizationRow)
    contact = (
        select(ClientAssignmentRow.user_id)
        .where(
            ClientAssignmentRow.organization_id == organization_id,
            ClientAssignmentRow.user_id == UserRow.id,
            ClientAssignmentRow.role == "client_contact",
        )
        .exists()
    )
    account_manager = (
        select(ClientAssignmentRow.user_id)
        .where(
            ClientAssignmentRow.client_id == client_id,
            ClientAssignmentRow.user_id == UserRow.id,
            ClientAssignmentRow.organization_id == ClientRow.organization_id,
            ClientAssignmentRow.role == "account_manager",
        )
        .exists()
    )
    return (
        select(UserRow.id, UserRow.email, OrganizationMemberRow.role)
        .select_from(UserRow)
        .join(OrganizationMemberRow, and_(OrganizationMemberRow.user_id == UserRow.id, OrganizationMemberRow.organization_id == organization_id))
        .join(workspace, workspace.id == organization_id)
        .join(ClientRow, ClientRow.id == client_id)
        .join(agency, agency.id == ClientRow.organization_id)
        .where(
            UserRow.disabled_at.is_(None),
            UserRow.system_role != CLIENT_ROLE,
            OrganizationMemberRow.status == "active",
            OrganizationMemberRow.role.in_(("owner", "admin", "member")),
            workspace.status == "active",
            ClientRow.status == "active",
            agency.status == "active",
            agency.customer_client_id.is_(None),
            or_(
                and_(workspace.customer_client_id.is_(None), ClientRow.organization_id == workspace.id),
                and_(workspace.customer_client_id == ClientRow.id, ClientRow.organization_id != workspace.id),
            ),
            ~contact,
            or_(OrganizationMemberRow.role.in_(("owner", "admin")), and_(OrganizationMemberRow.role == "member", account_manager)),
        )
    )


def _participant_item(row):
    return {"user_id": row.id, "email": row.email, "role": row.role if row.role in {"owner", "admin"} else "account_manager"}


async def _participant_page(session, *, actor_id, organization_id, client_id, thread_id, portal, limit, cursor):
    scope = _participant_scope(actor_id, organization_id, client_id, thread_id)
    after = _decode_participant_cursor(cursor, scope=scope) if cursor is not None else None
    query = _eligible_participant_query(organization_id=organization_id, client_id=client_id)
    if after is not None:
        query = query.where(UserRow.id > after)
    rows = (await session.execute(query.order_by(UserRow.id).limit(limit + 1))).all()
    page = rows[:limit]
    has_more = len(rows) > limit
    plan = portal.work_plan if isinstance(portal.work_plan, dict) else {}
    selected_ids = sorted({value for value in (plan.get("assignee_user_id"), plan.get("verifier_user_id")) if isinstance(value, str) and 0 < len(value) <= 64})
    selected_rows = []
    if selected_ids:
        selected_rows = (await session.execute(_eligible_participant_query(organization_id=organization_id, client_id=client_id).where(UserRow.id.in_(selected_ids)).order_by(UserRow.id))).all()
    selected = [_participant_item(row) for row in selected_rows]
    return {
        "schema": "work_plan_participants.v1",
        "source": {"thread_id": thread_id},
        "plan_revision": portal.work_plan_revision,
        "items": [_participant_item(row) for row in page],
        "selected_items": selected,
        "limit": limit,
        "has_more": has_more,
        "next_cursor": _encode_participant_cursor(page[-1].id, scope=scope) if has_more else None,
    }


def work_plan_projection(portal):
    """Only callers that already established exact staff/client access use this."""
    stamp = portal.work_plan_updated_at
    if stamp is not None:
        stamp = (stamp.replace(tzinfo=UTC) if stamp.tzinfo is None else stamp.astimezone(UTC)).isoformat()
    return {
        "schema": "internal_work_plan.v1",
        "revision": portal.work_plan_revision,
        "plan": portal.work_plan,
        "recorded_by_user_id": portal.work_plan_updated_by_user_id,
        "recorded_at": stamp,
        "verification": "staff_recorded_unverified",
        "source": {"table": "board_portal", "id": portal.thread_id},
    }


async def read_work_plan(*, actor_id, organization_id, thread_id, scope: BoundWorkPlanScope | None = None, participants_cursor=None, include_participants=False):
    try:
        async with _factory()() as session:
            _, portal = await _scoped(session, actor_id=actor_id, organization_id=organization_id, thread_id=thread_id, scope=scope)
            result = work_plan_projection(portal)
            if include_participants and scope is not None:
                result["current_actor_user_id"] = actor_id
                result["participants"] = await _participant_page(
                    session,
                    actor_id=actor_id,
                    organization_id=organization_id,
                    client_id=scope.client_id,
                    thread_id=thread_id,
                    portal=portal,
                    limit=DEFAULT_PARTICIPANT_LIMIT,
                    cursor=participants_cursor,
                )
            return result
    except SQLAlchemyError:
        raise HTTPException(503, "Internal work plan could not be read") from None


async def read_work_plan_participants(*, actor_id, organization_id, thread_id, limit=DEFAULT_PARTICIPANT_LIMIT, cursor=None):
    if not 1 <= limit <= MAX_PARTICIPANT_LIMIT:
        raise HTTPException(422, "Work-plan participant limit must be between 1 and 100")
    try:
        async with _factory()() as session:
            thread, portal = await _scoped(session, actor_id=actor_id, organization_id=organization_id, thread_id=thread_id)
            return await _participant_page(
                session,
                actor_id=actor_id,
                organization_id=organization_id,
                client_id=thread.client_id,
                thread_id=thread_id,
                portal=portal,
                limit=limit,
                cursor=cursor,
            )
    except SQLAlchemyError:
        raise HTTPException(503, "Work-plan participants could not be read") from None


async def save_work_plan(*, actor_id, organization_id, thread_id, body: WorkPlanUpdate, scope: BoundWorkPlanScope | None = None):
    from app.gateway.client_context import _staff_client

    plan = body.plan.model_dump(mode="json")
    if len(json.dumps(plan, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > MAX_PLAN_BYTES:
        raise HTTPException(422, "Internal work plan must fit within 8000 bytes")
    if thread_id in body.plan.dependency_thread_ids:
        raise HTTPException(422, "A request cannot depend on itself")
    try:
        # Check before taking a write lock, then recheck inside it before mutation.
        async with _factory()() as session:
            await _scoped(session, actor_id=actor_id, organization_id=organization_id, thread_id=thread_id, scope=scope)
        async with _factory()() as session, session.begin():
            # Mirrors canonical customer provisioning: first write serializes SQLite
            # and PostgreSQL writers without changing the draft's revision.
            locked = await session.execute(update(BoardPortalRow).where(BoardPortalRow.thread_id == thread_id, BoardPortalRow.organization_id == organization_id).values(revision=BoardPortalRow.revision))
            if locked.rowcount != 1:
                raise HTTPException(404, "Internal work plan not found")
            thread, _ = await _scoped(session, actor_id=actor_id, organization_id=organization_id, thread_id=thread_id, scope=scope)
            for participant in {body.plan.assignee_user_id, body.plan.verifier_user_id} - {None}:
                await _staff_client(session, actor_id=participant, organization_id=organization_id, client_id=thread.client_id)
            dependencies = body.plan.dependency_thread_ids
            if dependencies:
                found = set(
                    await session.scalars(
                        select(BoardThreadRow.id)
                        .join(BoardPortalRow, BoardPortalRow.thread_id == BoardThreadRow.id)
                        .where(BoardThreadRow.id.in_(dependencies), BoardThreadRow.client_id == thread.client_id, BoardThreadRow.organization_id == organization_id, BoardPortalRow.organization_id == organization_id)
                    )
                )
                if found != set(dependencies):
                    raise HTTPException(404, "Dependency request not found")
            now = datetime.now(UTC)
            changed = await session.execute(
                update(BoardPortalRow)
                .where(BoardPortalRow.thread_id == thread_id, BoardPortalRow.organization_id == organization_id, BoardPortalRow.work_plan_revision == body.expected_revision)
                .values(work_plan=plan, work_plan_revision=body.expected_revision + 1, work_plan_updated_by_user_id=actor_id, work_plan_updated_at=now)
            )
            if changed.rowcount != 1:
                raise HTTPException(409, "Internal work plan changed; reload before saving")
            # Internal plans stay invisible to contacts: never bump the request's client-visible updated_at.
            portal = await session.get(BoardPortalRow, thread_id, populate_existing=True)
            return work_plan_projection(portal), thread.client_id
    except SQLAlchemyError:
        raise HTTPException(503, "Internal work plan could not be saved") from None


async def save_audited_work_plan(*, request, actor_id, organization_id, thread_id, body, storage_user_id, source="client_portal", scope=None):
    """Keep the existing HTTP save-then-best-effort-audit contract for both callers."""
    from app.gateway.deps import audit_actor_id, record_audit_event

    if scope is not None and audit_actor_id(request) != actor_id:
        raise HTTPException(404, "Bound internal work plan not found")
    result, client_id = await save_work_plan(actor_id=actor_id, organization_id=organization_id, thread_id=thread_id, body=body, scope=scope)
    await record_audit_event(
        request,
        action="client_portal.work_plan.saved",
        outcome="success",
        actor_user_id=audit_actor_id(request),
        organization_id=organization_id,
        target_type="client_portal_thread",
        target_id=thread_id,
        details={"source": source, "storage_user_id": storage_user_id, "client_id": client_id, "revision": result["revision"]},
    )
    return result


def bind_work_plan_access(*, request, actor_id, organization_id, storage_user_id, selected_scope, chat_id, run_id):
    """Called only after authenticated portal-work admission; never from tool args."""
    from pydantic import ValidationError

    from app.gateway.auth_disabled import AUTH_SOURCE_SESSION
    from app.gateway.deps import audit_actor_id
    from deerflow.tools.client_work_plan_access import ClientWorkPlanAccess

    auth = getattr(request.state, "auth", None)

    def identity_matches():
        return (
            auth is not None
            and getattr(request.state, "auth_source", None) == AUTH_SOURCE_SESSION  # PATs are barred from client-portal routes, so runs started by one get no plan tools
            and audit_actor_id(request) == actor_id
            and (auth.actor_user_id, auth.organization_id, auth.storage_user_id) == (actor_id, organization_id, storage_user_id)
        )

    if not actor_id or not identity_matches():
        return None
    request_id = selected_scope["thread_id"]
    scope = BoundWorkPlanScope(selected_scope["client_id"], chat_id, storage_user_id, selected_scope["project_id"])
    identity = {"actor_id": actor_id, "organization_id": organization_id, "thread_id": request_id, "scope": scope}

    async def read(participants_cursor=None):
        try:
            if not identity_matches():
                raise HTTPException(404, "Bound internal work plan not found")
            return await read_work_plan(**identity, participants_cursor=participants_cursor, include_participants=True)
        except HTTPException as exc:
            return {"status": exc.status_code, "error": exc.detail}

    async def authorize():
        if not identity_matches():
            raise HTTPException(404, "Bound internal work plan not found")
        await read_work_plan(**identity)

    async def update_plan(expected_revision, plan):
        try:
            if not identity_matches():
                raise HTTPException(404, "Bound internal work plan not found")
            body = WorkPlanUpdate.model_validate({"expected_revision": expected_revision, "plan": plan})
            return await save_audited_work_plan(request=request, **identity, body=body, storage_user_id=storage_user_id, source="client_work_plan_tool")
        except HTTPException as exc:
            return {"status": exc.status_code, "error": exc.detail}
        except ValidationError:
            return {"status": 422, "error": "Invalid internal work plan; use the documented fields and bounds"}

    return ClientWorkPlanAccess(actor_id, organization_id, storage_user_id, scope.client_id, request_id, chat_id, run_id, authorize, read, update_plan)
