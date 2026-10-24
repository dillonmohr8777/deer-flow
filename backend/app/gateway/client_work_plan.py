"""Recorded internal planning on an existing portal request; no execution."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import HTTPException
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError

from deerflow.persistence.board.model import BoardPortalRow, BoardThreadRow

RecordId = Annotated[str, Field(min_length=1, max_length=64)]
MAX_PLAN_BYTES = 8000


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


async def _scoped(session, *, actor_id, organization_id, thread_id):
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
    return pair


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


async def read_work_plan(*, actor_id, organization_id, thread_id):
    try:
        async with _factory()() as session:
            _, portal = await _scoped(session, actor_id=actor_id, organization_id=organization_id, thread_id=thread_id)
            return work_plan_projection(portal)
    except SQLAlchemyError:
        raise HTTPException(503, "Internal work plan could not be read") from None


async def save_work_plan(*, actor_id, organization_id, thread_id, body: WorkPlanUpdate):
    from app.gateway.client_context import _staff_client

    plan = body.plan.model_dump(mode="json")
    if len(json.dumps(plan, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > MAX_PLAN_BYTES:
        raise HTTPException(422, "Internal work plan must fit within 8000 bytes")
    if thread_id in body.plan.dependency_thread_ids:
        raise HTTPException(422, "A request cannot depend on itself")
    try:
        # Check before taking a write lock, then recheck inside it before mutation.
        async with _factory()() as session:
            await _scoped(session, actor_id=actor_id, organization_id=organization_id, thread_id=thread_id)
        async with _factory()() as session, session.begin():
            # Mirrors canonical customer provisioning: first write serializes SQLite
            # and PostgreSQL writers without changing the draft's revision.
            locked = await session.execute(update(BoardPortalRow).where(BoardPortalRow.thread_id == thread_id, BoardPortalRow.organization_id == organization_id).values(revision=BoardPortalRow.revision))
            if locked.rowcount != 1:
                raise HTTPException(404, "Internal work plan not found")
            thread, _ = await _scoped(session, actor_id=actor_id, organization_id=organization_id, thread_id=thread_id)
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
            await session.execute(update(BoardThreadRow).where(BoardThreadRow.id == thread_id, BoardThreadRow.organization_id == organization_id).values(updated_at=now))
            portal = await session.get(BoardPortalRow, thread_id, populate_existing=True)
            return work_plan_projection(portal), thread.client_id
    except SQLAlchemyError:
        raise HTTPException(503, "Internal work plan could not be saved") from None
