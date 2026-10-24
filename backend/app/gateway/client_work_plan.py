"""Recorded internal planning on an existing portal request; no execution."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import HTTPException
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError

from deerflow.persistence.board.model import BoardPortalRow, BoardThreadRow

RecordId = Annotated[str, Field(min_length=1, max_length=64)]
MAX_PLAN_BYTES = 8000


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
        for participant in _participant_choices(portal, actor_id):
            await _staff_client(session, actor_id=participant, organization_id=organization_id, client_id=scope.client_id)
    return pair


def _participant_choices(portal, actor_id):
    plan = portal.work_plan or {}
    return sorted({actor_id, plan.get("assignee_user_id"), plan.get("verifier_user_id")} - {None})


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


async def read_work_plan(*, actor_id, organization_id, thread_id, scope: BoundWorkPlanScope | None = None):
    try:
        async with _factory()() as session:
            _, portal = await _scoped(session, actor_id=actor_id, organization_id=organization_id, thread_id=thread_id, scope=scope)
            result = work_plan_projection(portal)
            if scope is not None:
                result["participant_user_ids"] = _participant_choices(portal, actor_id)
            return result
    except SQLAlchemyError:
        raise HTTPException(503, "Internal work plan could not be read") from None


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
            thread, current_portal = await _scoped(session, actor_id=actor_id, organization_id=organization_id, thread_id=thread_id, scope=scope)
            for participant in {body.plan.assignee_user_id, body.plan.verifier_user_id} - {None}:
                await _staff_client(session, actor_id=participant, organization_id=organization_id, client_id=thread.client_id)
                if scope is not None and participant not in _participant_choices(current_portal, actor_id):
                    raise HTTPException(404, "Internal work plan participant is unavailable")
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
            await session.execute(update(BoardThreadRow).where(BoardThreadRow.id == thread_id, BoardThreadRow.organization_id == organization_id).values(updated_at=now))
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

    from app.gateway.auth_disabled import AUTH_SOURCE_PAT, AUTH_SOURCE_SESSION
    from app.gateway.deps import audit_actor_id
    from deerflow.tools.client_work_plan_access import ClientWorkPlanAccess

    auth = getattr(request.state, "auth", None)

    def identity_matches():
        return (
            auth is not None
            and getattr(request.state, "auth_source", None) in {AUTH_SOURCE_SESSION, AUTH_SOURCE_PAT}
            and audit_actor_id(request) == actor_id
            and (auth.actor_user_id, auth.organization_id, auth.storage_user_id) == (actor_id, organization_id, storage_user_id)
        )

    if not actor_id or not identity_matches():
        return None
    request_id = selected_scope["thread_id"]
    scope = BoundWorkPlanScope(selected_scope["client_id"], chat_id, storage_user_id, selected_scope["project_id"])
    identity = {"actor_id": actor_id, "organization_id": organization_id, "thread_id": request_id, "scope": scope}

    async def read():
        try:
            if not identity_matches():
                raise HTTPException(404, "Bound internal work plan not found")
            return await read_work_plan(**identity)
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
