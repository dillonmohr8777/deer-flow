"""Personal morning brief: what moved, what's due, and what's waiting, across a person's clients.

``GET /api/briefs/today`` is a read-only reporting endpoint computed deterministically
from existing tables (no model call), mirroring ``console.py``'s pattern: short-lived
queries against harness-owned tables via ``get_session_factory()`` directly, no new
store methods. Requires a SQL database backend; 503 on the memory backend.

Scope resolution (projects.client_id may be empty for a while yet):
1. The caller's assigned clients come from ``client_repo.list_mine()``, joined on
   ``client_assignments.user_id``, which is the *actor* (the human), not the
   workspace *storage* principal a shared workspace writes content under. Every
   other table below is scoped by content ownership (``get_current_user()``,
   the storage principal), matching ``console.py``/``projects.py``. The two only
   diverge in a shared workspace, and client_assignments is specifically a
   per-person roster, so it alone uses the actor id.
2. Active projects linked to those clients (``projects.client_id``) become the
   brief's project scope. Almost nothing sets that column yet, so an empty result
   falls back to the caller's own active projects, so the brief stays useful before
   client/project linking exists in practice.

"Waiting on you" combines two DB-exposed signals for the *latest* run per thread
in scope (older superseded runs don't count: a reply already moved things on):
``runs.status == "interrupted"`` (rollback/cancel admission), or a run that ended
on an unanswered clarification/approval card. The latter has no persisted
"unanswered" flag: ``ask_clarification`` and the sandbox network prompt end the
graph normally (status "success") with the request in a trailing ToolMessage
artifact (see backend/docs/RUN_INTERACTION_POLICY.md and worker.py's
``_ends_on_human_input_request``). Parsing checkpoint state per thread is too
expensive for a bounded list endpoint; the run_events row the same middleware
already journals (``llm.human.input``, runtime/events/catalog.py) is the cheap,
SQL-queryable proxy: present on a run with no later run on that thread, it means
nobody has replied yet.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, time, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.gateway.authz import require_permission
from app.gateway.deps import get_current_user
from deerflow.persistence.clients import ClientRepository
from deerflow.persistence.engine import get_session_factory
from deerflow.persistence.models.run_event import RunEventRow
from deerflow.persistence.projects.model import ProjectDocumentRow, ProjectRow
from deerflow.persistence.run.model import RunRow
from deerflow.persistence.scheduled_task_runs.model import ScheduledTaskRunRow
from deerflow.persistence.scheduled_tasks.model import ScheduledTaskRow
from deerflow.persistence.thread_meta.model import ThreadMetaRow
from deerflow.runtime.user_context import get_workspace_actor_user_id, resolve_organization_id

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/briefs", tags=["briefs"])

_LOOKBACK_HOURS = 24
_FALLBACK_PROJECT_LIMIT = 50
_THREAD_SCAN_LIMIT = 200
_ACTIVITY_LIMIT = 50
_DUE_TODAY_LIMIT = 20
_WAITING_LIMIT = 20
_ERROR_EXCERPT_CHARS = 200


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class BriefClient(BaseModel):
    id: str
    display_name: str


class BriefActivityItem(BaseModel):
    """One thing that moved in the last 24 hours."""

    kind: str = Field(..., description="thread | run_success | run_failed | document | scheduled_task_success | scheduled_task_failed")
    title: str | None = None
    detail: str | None = Field(default=None, description="Error excerpt, when the item is a failure")
    project_id: str | None = None
    project_name: str | None = None
    client_id: str | None = None
    client_name: str | None = None
    thread_id: str | None = None
    agent_name: str | None = Field(default=None, description="Custom-agent name for thread routing, when set")
    occurred_at: datetime


class BriefDueTask(BaseModel):
    """A scheduled task whose next run falls today."""

    task_id: str
    title: str
    next_run_at: datetime
    thread_id: str | None = None


class BriefWaitingItem(BaseModel):
    """A thread whose latest run needs the person's attention."""

    kind: str = Field(..., description="interrupted | clarification")
    thread_id: str
    run_id: str
    title: str | None = None
    project_id: str | None = None
    project_name: str | None = None
    client_id: str | None = None
    client_name: str | None = None
    agent_name: str | None = None
    updated_at: datetime


class BriefTodayResponse(BaseModel):
    generated_at: datetime
    assigned_clients: list[BriefClient]
    activity: list[BriefActivityItem]
    due_today: list[BriefDueTask]
    waiting_on_you: list[BriefWaitingItem]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _session_factory_or_503():
    sf = get_session_factory()
    if sf is None:
        raise HTTPException(
            status_code=503,
            detail="Briefs require a SQL database backend; set database.backend to sqlite or postgres in config.yaml.",
        )
    return sf


def _owner_filters(model: Any, user_id: str | None) -> list:
    """The storage-user filter plus, when the request has one, the active organization filter."""
    filters = [model.user_id == user_id] if user_id else []
    if (organization_id := resolve_organization_id()) is not None:
        filters.append(model.organization_id == organization_id)
    return filters


def _as_utc(dt: datetime | None) -> datetime | None:
    """Normalize DB timestamps: SQLite round-trips them naive, Postgres aware."""
    if dt is None:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt


def _agent_name(metadata: dict | None) -> str | None:
    name = (metadata or {}).get("agent_name")
    return name if isinstance(name, str) and name else None


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.get(
    "/today",
    response_model=BriefTodayResponse,
    summary="Today's Brief",
    description="Personal, organization-scoped summary of what moved, what's due today, and what's waiting on the signed-in person, across their assigned clients.",
)
@require_permission("runs", "read")
async def briefs_today(
    request: Request,
    tz_offset_minutes: int = Query(default=0, ge=-840, le=840, description="Local-time offset from UTC for 'today' bucketing"),
) -> BriefTodayResponse:
    sf = _session_factory_or_503()
    user_id = await get_current_user(request)
    actor_user_id = get_workspace_actor_user_id()
    now = datetime.now(UTC)
    cutoff = now - timedelta(hours=_LOOKBACK_HOURS)
    tz_delta = timedelta(minutes=tz_offset_minutes)
    today_local = (now + tz_delta).date()
    day_start_utc = datetime.combine(today_local, time.min, tzinfo=UTC) - tz_delta
    day_end_utc = day_start_utc + timedelta(days=1)

    # 1. Assigned clients: actor-scoped (see module docstring), org-scoped inside list_mine().
    client_rows: list[dict] = []
    if actor_user_id is not None:
        client_rows = await ClientRepository(sf).list_mine()
    assigned_clients = [BriefClient(id=c["id"], display_name=c["display_name"]) for c in client_rows]
    assigned_client_ids = [c["id"] for c in client_rows]
    client_name_by_id = {c["id"]: c["display_name"] for c in client_rows}

    activity: list[BriefActivityItem] = []
    due_today: list[BriefDueTask] = []
    waiting_on_you: list[BriefWaitingItem] = []

    async with sf() as session:
        # 2. Project scope: clients' linked projects, else the person's own active ones.
        scope_projects: list[ProjectRow] = []
        if assigned_client_ids:
            stmt = select(ProjectRow).where(
                ProjectRow.client_id.in_(assigned_client_ids),
                ProjectRow.status == "active",
                *_owner_filters(ProjectRow, user_id),
            )
            scope_projects = list((await session.execute(stmt)).scalars())
        if not scope_projects:
            stmt = select(ProjectRow).where(ProjectRow.status == "active", *_owner_filters(ProjectRow, user_id)).order_by(ProjectRow.updated_at.desc()).limit(_FALLBACK_PROJECT_LIMIT)
            scope_projects = list((await session.execute(stmt)).scalars())

        project_ids = [p.id for p in scope_projects]
        project_name_by_id = {p.id: p.name for p in scope_projects}
        client_id_by_project = {p.id: p.client_id for p in scope_projects}

        def _project_context(project_id: str | None) -> dict:
            client_id = client_id_by_project.get(project_id) if project_id else None
            return {
                "project_id": project_id,
                "project_name": project_name_by_id.get(project_id) if project_id else None,
                "client_id": client_id,
                "client_name": client_name_by_id.get(client_id) if client_id else None,
            }

        thread_rows: list[Any] = []
        if project_ids:
            stmt = (
                select(ThreadMetaRow)
                .where(
                    ThreadMetaRow.project_id.in_(project_ids),
                    *_owner_filters(ThreadMetaRow, user_id),
                )
                .limit(_THREAD_SCAN_LIMIT)
            )
            thread_rows = list((await session.execute(stmt)).scalars())
        thread_by_id = {t.thread_id: t for t in thread_rows}
        scope_thread_ids = list(thread_by_id)

        # 3a. New threads in the last 24h.
        for t in thread_rows:
            created = _as_utc(t.created_at)
            if created is None or created < cutoff:
                continue
            ctx = _project_context(t.project_id)
            activity.append(
                BriefActivityItem(
                    kind="thread",
                    title=t.display_name,
                    thread_id=t.thread_id,
                    agent_name=_agent_name(t.metadata_json),
                    occurred_at=created,
                    **ctx,
                )
            )

        # 3b. New runs in the last 24h, in scope-project threads.
        if scope_thread_ids:
            stmt = select(RunRow).where(
                RunRow.thread_id.in_(scope_thread_ids),
                RunRow.operation_kind == "run",
                RunRow.created_at >= cutoff,
                *_owner_filters(RunRow, user_id),
            )
            for run in (await session.execute(stmt)).scalars():
                thread = thread_by_id.get(run.thread_id)
                ctx = _project_context(thread.project_id if thread else None)
                activity.append(
                    BriefActivityItem(
                        kind="run_failed" if run.status in ("error", "timeout") else "run_success",
                        title=thread.display_name if thread else None,
                        detail=run.error[:_ERROR_EXCERPT_CHARS] if run.error else None,
                        thread_id=run.thread_id,
                        agent_name=_agent_name(thread.metadata_json) if thread else None,
                        occurred_at=_as_utc(run.created_at),
                        **ctx,
                    )
                )

            # 3d. Waiting on you: the latest run per scope thread, if interrupted or
            # still sitting on an unanswered clarification/approval card.
            latest_at = (
                select(RunRow.thread_id, func.max(RunRow.created_at).label("latest_created_at"))
                .where(
                    RunRow.thread_id.in_(scope_thread_ids),
                    RunRow.operation_kind == "run",
                    *_owner_filters(RunRow, user_id),
                )
                .group_by(RunRow.thread_id)
                .subquery()
            )
            # ponytail: ties on created_at within one thread are vanishingly rare in
            # practice (real wall-clock timestamps); breaking them would need a
            # second ordering column that runs.created_at doesn't carry today.
            stmt = (
                select(RunRow)
                .join(
                    latest_at,
                    (RunRow.thread_id == latest_at.c.thread_id) & (RunRow.created_at == latest_at.c.latest_created_at),
                )
                .where(RunRow.operation_kind == "run")
            )
            latest_runs = list((await session.execute(stmt)).scalars())

            human_input_run_ids: set[str] = set()
            candidate_run_ids = [r.run_id for r in latest_runs if r.status == "success"]
            if candidate_run_ids:
                ev_stmt = (
                    select(RunEventRow.run_id)
                    .where(
                        RunEventRow.run_id.in_(candidate_run_ids),
                        RunEventRow.event_type == "llm.human.input",
                    )
                    .distinct()
                )
                human_input_run_ids = {rid for (rid,) in (await session.execute(ev_stmt)).all()}

            for run in latest_runs:
                if run.status == "interrupted":
                    kind = "interrupted"
                elif run.run_id in human_input_run_ids:
                    kind = "clarification"
                else:
                    continue
                thread = thread_by_id.get(run.thread_id)
                ctx = _project_context(thread.project_id if thread else None)
                waiting_on_you.append(
                    BriefWaitingItem(
                        kind=kind,
                        thread_id=run.thread_id,
                        run_id=run.run_id,
                        title=thread.display_name if thread else None,
                        agent_name=_agent_name(thread.metadata_json) if thread else None,
                        updated_at=_as_utc(run.updated_at),
                        **ctx,
                    )
                )

        # 3c. Documents added to project shelves in the last 24h.
        if project_ids:
            stmt = select(ProjectDocumentRow).where(
                ProjectDocumentRow.project_id.in_(project_ids),
                ProjectDocumentRow.created_at >= cutoff,
                ProjectDocumentRow.trashed_at.is_(None),
                *_owner_filters(ProjectDocumentRow, user_id),
            )
            for doc in (await session.execute(stmt)).scalars():
                ctx = _project_context(doc.project_id)
                activity.append(
                    BriefActivityItem(
                        kind="document",
                        title=doc.name,
                        occurred_at=_as_utc(doc.created_at),
                        **ctx,
                    )
                )

        # 3e. Scheduled-task outcomes in the last 24h, including failures. Tasks
        # aren't linked to projects, so this is owner-scoped only (module docstring).
        stmt = (
            select(ScheduledTaskRunRow, ScheduledTaskRow.title)
            .join(ScheduledTaskRow, ScheduledTaskRow.id == ScheduledTaskRunRow.task_id)
            .where(
                ScheduledTaskRunRow.finished_at.is_not(None),
                ScheduledTaskRunRow.finished_at >= cutoff,
                *_owner_filters(ScheduledTaskRow, user_id),
            )
        )
        for occurrence, title in (await session.execute(stmt)).all():
            activity.append(
                BriefActivityItem(
                    kind="scheduled_task_failed" if occurrence.status == "failed" else "scheduled_task_success",
                    title=title,
                    detail=occurrence.error[:_ERROR_EXCERPT_CHARS] if occurrence.error else None,
                    thread_id=occurrence.thread_id,
                    occurred_at=_as_utc(occurrence.finished_at),
                )
            )

        activity.sort(key=lambda item: item.occurred_at, reverse=True)
        activity = activity[:_ACTIVITY_LIMIT]

        # 4. Due today: scheduled tasks whose next run falls in the caller's local day.
        stmt = (
            select(ScheduledTaskRow)
            .where(
                ScheduledTaskRow.status == "enabled",
                ScheduledTaskRow.next_run_at.is_not(None),
                ScheduledTaskRow.next_run_at >= day_start_utc,
                ScheduledTaskRow.next_run_at < day_end_utc,
                *_owner_filters(ScheduledTaskRow, user_id),
            )
            .order_by(ScheduledTaskRow.next_run_at.asc())
            .limit(_DUE_TODAY_LIMIT)
        )
        for task in (await session.execute(stmt)).scalars():
            due_today.append(
                BriefDueTask(
                    task_id=task.id,
                    title=task.title,
                    next_run_at=_as_utc(task.next_run_at),
                    thread_id=task.thread_id,
                )
            )

        # Oldest-waiting-first: the longest-stalled item is the most actionable.
        waiting_on_you.sort(key=lambda item: item.updated_at)
        waiting_on_you = waiting_on_you[:_WAITING_LIMIT]

    return BriefTodayResponse(
        generated_at=now,
        assigned_clients=assigned_clients,
        activity=activity,
        due_today=due_today,
        waiting_on_you=waiting_on_you,
    )
