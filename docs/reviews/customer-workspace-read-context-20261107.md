# Customer workspace read access: immutable review context

This source artifact supplies unchanged dependencies omitted from the changed-file-only review transport. It carries code and provenance, not a review verdict. The ordinary primary and final reviews still decide the change.

Source commit: `a1d995655509e30f76007ab4c696119d1d100671`. Every module below is included in full, byte-for-byte, with its SHA-256. These modules are unchanged by this PR; the changed client boundary, task projection, pages, and tests are supplied separately by the normal packet.

Coverage: project metadata and document routes; scoped project/document repositories; filesystem content validation and response serving; permission checks; effective actor/storage/organization resolution; project fetch and download URL creation; workspace selection and account/logout cache lifecycle. This does not include every transitive framework, persistence-model, or middleware dependency. Imports are retained so any remaining gap is visible.

The workspace hook performs a hard navigation after selecting a workspace. The authentication provider clears its shared query client on logout and reloads when a confirmed signed-in identity changes. These observations are navigation to the implementations below, not substitutes for reviewing them.

| Source path | Bytes | SHA-256 |
| --- | ---: | --- |
| `backend/app/gateway/routers/projects.py` | 11589 | `4aab20a2dc496935c692564413b7978ecfd69f0dd30b761590150803d33c513b` |
| `backend/packages/harness/deerflow/persistence/projects/sql.py` | 47370 | `c6a23d7eece8ec827cb68810c0590aae886860d3f1409c309662d96e87b67117` |
| `frontend/src/core/projects/api.ts` | 17954 | `e1ab51155c21f5c5b7f9c3da5f9bec18aefa93bc63f4edfdef06d90e64135477` |
| `frontend/src/core/workspaces/hooks.ts` | 1504 | `2b7ffb49ca64a8316569e9bcb9bd907a575baa86e2469846ae8fa7621e817dbf` |
| `frontend/src/components/query-client-provider.tsx` | 614 | `b836ddaecf685e3cbd040661637bd6f7aa818a0c972afd91db5fc83e37fd0d2d` |
| `frontend/src/core/auth/AuthProvider.tsx` | 9196 | `dfe688f59299579a62ec2654c4d16634e77a14bb84f4545e53988684d4907d1b` |
| `backend/app/gateway/routers/project_documents.py` | 23014 | `30b17f5d5b4352583e9571f52d081c7d68cfbcb92c8995b4fca7993b2b550700` |
| `backend/packages/harness/deerflow/projects/documents.py` | 25970 | `6d8151480bea1f7118ac29c7c5a0c0ca9ba3b72c64705007dbeffc26829dd27e` |
| `backend/app/gateway/authz.py` | 37761 | `ad89dcdc3e6791b1acd12c89cba02b3d897ee2e14c97be4534db0fb036130c3d` |
| `backend/packages/harness/deerflow/runtime/user_context.py` | 17769 | `5e028b444ea292160e8543497c7f399d9822ded43c420de8e41d94acedc5db72` |

## backend/app/gateway/routers/projects.py

````python
"""CRUD API for projects (Phase 1: organization only — no documents/trash)."""

import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator

from app.gateway.authz import get_auth_context, require_permission
from app.gateway.deps import get_config, get_entitlement_repo, get_project_repo, get_thread_store
from deerflow.authz.entitlements import evaluate_entitlement
from deerflow.config.app_config import AppConfig, get_app_config
from deerflow.config.entitlement_config import resolve_current_entitlement_config
from deerflow.config.projects_config import ProjectsConfig
from deerflow.runtime.secret_context import redact_metadata_secrets
from deerflow.utils.time import coerce_iso

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/projects", tags=["projects"])

ProjectStatus = Literal["active", "archived"]


class ProjectResponse(BaseModel):
    id: str
    name: str
    client_id: str | None = None
    instructions: str
    presentation: dict
    status: str
    created_at: str
    updated_at: str


class ProjectCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    client_id: str | None = Field(default=None, description="Optional canonical client link; omitted or null creates an unbound project.")
    instructions: str = ""
    presentation: dict = Field(default_factory=dict)


class ProjectPatchRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    client_id: str | None = Field(default=None, description="An explicit null clears the binding; omission preserves it.")
    instructions: str | None = None
    presentation: dict | None = None


class ProjectListResponse(BaseModel):
    projects: list[ProjectResponse]


class ProjectsConfigResponse(BaseModel):
    """The projects-block knobs the UI needs before it can validate client-side."""

    instructions_max_bytes: int
    trash_retention_days: int


class ProjectThreadResponse(BaseModel):
    """A thread row from ``GET /api/projects/{id}/threads``.

    Deliberately narrow — only the fields ``ProjectThread`` declares in
    ``frontend/src/core/projects/types.ts``. Store rows carry ownership
    columns (``user_id``, ``assistant_id``) and ``ThreadMetaRow`` may grow;
    without this model those would leak onto the wire and the route's
    OpenAPI schema stays empty. Metadata is redacted here exactly as the
    surrounding thread endpoints redact it via ``_MetadataRedactingResponse``.
    """

    thread_id: str
    display_name: str | None = None
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata", mode="before", check_fields=False)
    @classmethod
    def _redact_metadata_secrets(cls, value: Any) -> Any:
        return redact_metadata_secrets(value)


def _to_response(row: dict) -> ProjectResponse:
    return ProjectResponse(
        id=row["id"],
        name=row["name"],
        client_id=row.get("client_id"),
        instructions=row.get("instructions", ""),
        presentation=row.get("presentation") or {},
        status=row["status"],
        created_at=row.get("created_at", ""),
        updated_at=row.get("updated_at", ""),
    )


async def _require_project_binding_authority(request: Request, client_id: str | None) -> None:
    """Require an active workspace owner/admin and, when linking, staff access to the exact client."""
    auth = get_auth_context(request)
    actor_id = getattr(auth, "actor_user_id", None)
    organization_id = getattr(auth, "organization_id", None)
    from deerflow.runtime.user_context import resolve_organization_id

    if not actor_id or not organization_id or resolve_organization_id() != organization_id:
        raise HTTPException(status_code=403, detail="An active workspace owner or admin is required to change a project client binding.")

    # Re-read active membership from the database; neither a global admin role nor
    # an auth snapshot from another workspace grants this metadata mutation.
    from app.gateway.routers.clients import _is_active_org_admin

    if not await _is_active_org_admin(str(actor_id)):
        raise HTTPException(status_code=403, detail="Only an active workspace owner or admin can change a project client binding.")
    if client_id is not None:
        from app.gateway.client_context import require_staff_client

        await require_staff_client(actor_id=str(actor_id), organization_id=str(organization_id), client_id=client_id)


def _not_found() -> HTTPException:
    # Fail closed: foreign projects are indistinguishable from missing ones.
    return HTTPException(status_code=404, detail="Project not found")


def _projects_config() -> ProjectsConfig:
    """Projects config, falling back to defaults when the app config is unavailable."""
    try:
        return get_app_config().projects
    except (FileNotFoundError, RuntimeError):
        return ProjectsConfig()


def _validate_instructions_length(instructions: str | None) -> None:
    """Reject oversized instructions with 422 — never truncate (spec §6.5/§11).

    The cap counts UTF-8 bytes, so multi-byte characters cost their encoded
    length rather than one character each.
    """
    if instructions is None:
        return
    max_bytes = _projects_config().instructions_max_bytes
    if len(instructions.encode("utf-8")) > max_bytes:
        raise HTTPException(status_code=422, detail=f"instructions exceeds the configured {max_bytes}-byte UTF-8 limit")


@router.post("", response_model=ProjectResponse, status_code=201)
@require_permission("projects", "write")
async def create_project(body: ProjectCreateRequest, request: Request) -> ProjectResponse:
    _validate_instructions_length(body.instructions)
    if body.client_id is not None:
        await _require_project_binding_authority(request, body.client_id)
    repo = get_project_repo(request)
    await _check_projects_max_entitlement(request, repo)
    return _to_response(await repo.create(name=body.name, client_id=body.client_id, instructions=body.instructions, presentation=body.presentation))


async def _check_projects_max_entitlement(request: Request, repo: Any) -> None:
    """Inline ``projects.max`` limit check (design §3: a limit key needs the
    caller's live usage count, so it cannot be a bare decorator).
    """
    entitlement_config = resolve_current_entitlement_config()
    if not entitlement_config.enabled:
        return

    auth = get_auth_context(request)
    organization_id = auth.organization_id if auth is not None else None
    current_usage = len(await repo.list(status="active"))
    decision = await evaluate_entitlement(
        get_entitlement_repo(request),
        organization_id,
        "projects.max",
        current_usage=current_usage,
        config=entitlement_config,
    )
    if not decision.allowed:
        raise HTTPException(
            status_code=403,
            detail={"error": "entitlement_exceeded", "key": "projects.max", "reason": decision.reason, "limit": decision.limit, "used": decision.used},
        )


@router.get("", response_model=ProjectListResponse)
@require_permission("projects", "read")
async def list_projects(request: Request, status: ProjectStatus | None = None) -> ProjectListResponse:
    repo = get_project_repo(request)
    return ProjectListResponse(projects=[_to_response(r) for r in await repo.list(status=status)])


@router.get("/config", response_model=ProjectsConfigResponse)
@require_permission("projects", "read")
async def get_projects_config(request: Request, config: AppConfig = Depends(get_config)) -> ProjectsConfigResponse:
    """Projects config for the UI (instructions byte cap, trash retention).

    Declared before ``/{project_id}`` so ``config`` is never swallowed as a
    project id. Values come from the live ``projects`` config block; when the
    block is absent the ``ProjectsConfig`` defaults apply.
    """
    return ProjectsConfigResponse(
        instructions_max_bytes=config.projects.instructions_max_bytes,
        trash_retention_days=config.projects.trash_retention_days,
    )


@router.get("/{project_id}", response_model=ProjectResponse)
@require_permission("projects", "read")
async def get_project(project_id: str, request: Request) -> ProjectResponse:
    row = await get_project_repo(request).get(project_id)
    if row is None:
        raise _not_found()
    return _to_response(row)


@router.patch("/{project_id}", response_model=ProjectResponse)
@require_permission("projects", "write")
async def patch_project(project_id: str, body: ProjectPatchRequest, request: Request) -> ProjectResponse:
    _validate_instructions_length(body.instructions)
    repo = get_project_repo(request)
    binding_requested = "client_id" in body.model_fields_set
    if binding_requested:
        # Preserve project ACL behavior before evaluating the new binding field.
        if await repo.get(project_id) is None:
            raise _not_found()
        await _require_project_binding_authority(request, body.client_id)
    patch_fields: dict[str, Any] = {"name": body.name, "instructions": body.instructions, "presentation": body.presentation}
    if binding_requested:
        patch_fields["client_id"] = body.client_id
    row = await repo.patch(project_id, **patch_fields)
    if row is None:
        raise _not_found()
    return _to_response(row)


@router.post("/{project_id}/archive", response_model=ProjectResponse)
@require_permission("projects", "write")
async def archive_project(project_id: str, request: Request) -> ProjectResponse:
    row = await get_project_repo(request).set_status(project_id, "archived")
    if row is None:
        raise _not_found()
    return _to_response(row)


@router.post("/{project_id}/restore", response_model=ProjectResponse)
@require_permission("projects", "write")
async def restore_project(project_id: str, request: Request) -> ProjectResponse:
    row = await get_project_repo(request).set_status(project_id, "active")
    if row is None:
        raise _not_found()
    return _to_response(row)


@router.delete("/{project_id}", status_code=204)
@require_permission("projects", "delete")
async def delete_project(project_id: str, request: Request) -> None:
    if not await get_project_repo(request).delete(project_id):
        raise _not_found()


@router.get("/{project_id}/threads", response_model=list[ProjectThreadResponse])
@require_permission("projects", "read")
@require_permission("threads", "read")
async def list_project_threads(project_id: str, request: Request, limit: int = Query(default=100, ge=1, le=1000), offset: int = Query(default=0, ge=0)) -> list[ProjectThreadResponse]:
    if await get_project_repo(request).get(project_id) is None:
        raise _not_found()
    # Active members only, mirroring the sidebar's `archived: false` lists:
    # an archived chat leaves the project's pages the same way it leaves the
    # sidebar and returns only via the global Archived tab.
    rows = await get_thread_store(request).search(
        project_id=project_id,
        archived=False,
        limit=limit,
        offset=offset,
    )
    return [
        ProjectThreadResponse(
            thread_id=r["thread_id"],
            display_name=r.get("display_name"),
            created_at=coerce_iso(r.get("created_at", "")),
            updated_at=coerce_iso(r.get("updated_at", "")),
            metadata=r.get("metadata", {}),
        )
        for r in rows
    ]
````

## backend/packages/harness/deerflow/persistence/projects/sql.py

````python
"""SQLAlchemy-backed project repositories.

Ownership discipline mirrors ``ThreadMetaRepository``: every method resolves
the caller via ``resolve_user_id(..., AUTO)`` and filters by ``user_id``;
a foreign project/document is indistinguishable from a missing one (callers
map ``None``/``False`` to 404). ``delete`` runs the membership-clearing
transaction from RFC v2 §5.1 plus the Phase-2 shelf-trash statement (§8.1):
every active ``project_documents`` row is moved to trash — with a
``trash_origin`` snapshot — inside the same transaction and row lock, so a
deleted project never leaves an active shelf row behind. No filesystem work
happens in either repository: shelf bytes are immutable, hash-qualified, and
owned by the document row's exclusive namespace, so trash and project delete
are pure row transitions.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.organizations.resolution import organization_from_owned_parent, private_organization_for_user
from deerflow.persistence.projects.model import ProjectDocumentRow, ProjectRow
from deerflow.persistence.thread_meta.model import ThreadMetaRow
from deerflow.runtime.user_context import AUTO, _AutoSentinel, resolve_organization_id, resolve_user_id
from deerflow.utils.file_io import await_drained
from deerflow.utils.time import coerce_iso

logger = logging.getLogger(__name__)

ProjectStatus = Literal["active", "archived"]


class _UnsetClientId:
    __slots__ = ()


_UNSET_CLIENT_ID = _UnsetClientId()


class ProjectNotAssignableError(ValueError):
    """Raised when a thread cannot be assigned to a project.

    The project is missing, foreign to the caller, or archived — the
    atomicity rules (RFC v2 §5.2) make these indistinguishable inside the
    mutating statement, so callers get one signal and map it to 404 (explicit
    API) or a dropped key (run admission).
    """


class ProjectRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @staticmethod
    def _row_to_dict(row: ProjectRow) -> dict[str, Any]:
        d = row.to_dict()
        for key in ("created_at", "updated_at"):
            val = d.get(key)
            if isinstance(val, datetime):
                d[key] = coerce_iso(val)
        return d

    async def create(
        self,
        *,
        name: str,
        client_id: str | None = None,
        instructions: str = "",
        presentation: dict | None = None,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> dict:
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectRepository.create")
        now = datetime.now(UTC)
        row = ProjectRow(
            id=uuid.uuid4().hex,
            user_id=resolved_user_id,
            name=name,
            client_id=client_id,
            instructions=instructions,
            presentation=presentation or {},
            status="active",
            created_at=now,
            updated_at=now,
        )
        async with self._sf() as session:
            row.organization_id = await private_organization_for_user(session, resolved_user_id)
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return self._row_to_dict(row)

    async def get(self, project_id: str, *, user_id: str | None | _AutoSentinel = AUTO) -> dict | None:
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectRepository.get")
        resolved_organization_id = resolve_organization_id()
        async with self._sf() as session:
            row = await session.get(ProjectRow, project_id)
            if row is None:
                return None
            if resolved_user_id is not None and row.user_id != resolved_user_id:
                return None
            if resolved_organization_id is not None and row.organization_id != resolved_organization_id:
                return None
            return self._row_to_dict(row)

    async def list(
        self,
        *,
        status: ProjectStatus | None = None,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> list[dict]:
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectRepository.list")
        resolved_organization_id = resolve_organization_id()
        stmt = select(ProjectRow).order_by(ProjectRow.created_at.asc(), ProjectRow.id.asc())
        if resolved_user_id is not None:
            stmt = stmt.where(ProjectRow.user_id == resolved_user_id)
        if resolved_organization_id is not None:
            stmt = stmt.where(ProjectRow.organization_id == resolved_organization_id)
        if status is not None:
            stmt = stmt.where(ProjectRow.status == status)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(r) for r in result.scalars()]

    async def patch(
        self,
        project_id: str,
        *,
        name: str | None = None,
        client_id: str | None | _UnsetClientId = _UNSET_CLIENT_ID,
        instructions: str | None = None,
        presentation: dict | None = None,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> dict | None:
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectRepository.patch")
        resolved_organization_id = resolve_organization_id()
        async with self._sf() as session:
            row = await session.get(ProjectRow, project_id)
            if row is None or (resolved_user_id is not None and row.user_id != resolved_user_id) or (resolved_organization_id is not None and row.organization_id != resolved_organization_id):
                return None
            if name is not None:
                row.name = name
            if not isinstance(client_id, _UnsetClientId):
                row.client_id = client_id
            if instructions is not None:
                row.instructions = instructions
            if presentation is not None:
                row.presentation = presentation
            await session.commit()
            await session.refresh(row)
            return self._row_to_dict(row)

    async def set_status(
        self,
        project_id: str,
        status: ProjectStatus,
        *,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> dict | None:
        """Idempotent status flip; returns the current row or None (missing/foreign)."""
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectRepository.set_status")
        resolved_organization_id = resolve_organization_id()
        async with self._sf() as session:
            row = await session.get(ProjectRow, project_id)
            if row is None or (resolved_user_id is not None and row.user_id != resolved_user_id) or (resolved_organization_id is not None and row.organization_id != resolved_organization_id):
                return None
            row.status = status
            await session.commit()
            await session.refresh(row)
            return self._row_to_dict(row)

    async def delete(self, project_id: str, *, user_id: str | None | _AutoSentinel = AUTO) -> bool:
        """Delete a project and clear membership in one transaction (no filesystem work).

        Returns True when the project row was deleted; False when missing/foreign.
        """
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectRepository.delete")
        resolved_organization_id = resolve_organization_id()
        async with self._sf() as session:
            async with session.begin():
                # Lock the project row before touching it (FOR UPDATE on
                # Postgres; the clause renders nothing on SQLite). Membership
                # assignment (ThreadMetaRepository.set_project/create) takes
                # the same row lock before writing ``project_id``, so an
                # assigner either commits first and has its membership cleared
                # below, or blocks until this transaction commits and then
                # re-reads the row as gone — no dangling ``threads_meta.project_id``
                # (RFC v2 §14.14). Missing/foreign rows keep the False result.
                lock_stmt = select(ProjectRow).where(ProjectRow.id == project_id)
                if resolved_user_id is not None:
                    lock_stmt = lock_stmt.where(ProjectRow.user_id == resolved_user_id)
                if resolved_organization_id is not None:
                    lock_stmt = lock_stmt.where(ProjectRow.organization_id == resolved_organization_id)
                locked = (await session.execute(lock_stmt.with_for_update())).scalar_one_or_none()
                if locked is None:
                    return False
                # §8.1 statement 2: every active shelf row moves to trash in
                # the same transaction and lock — never an active row pointing
                # at a deleted project. No filesystem work.
                await ProjectDocumentRepository.trash_all_for_project(session, project_id, project_name=locked.name, user_id=resolved_user_id, organization_id=resolved_organization_id)
                thread_update = update(ThreadMetaRow).where(ThreadMetaRow.project_id == project_id)
                delete_stmt = sa_delete(ProjectRow).where(ProjectRow.id == project_id)
                if resolved_user_id is not None:
                    thread_update = thread_update.where(ThreadMetaRow.user_id == resolved_user_id)
                    delete_stmt = delete_stmt.where(ProjectRow.user_id == resolved_user_id)
                if resolved_organization_id is not None:
                    thread_update = thread_update.where(ThreadMetaRow.organization_id == resolved_organization_id)
                    delete_stmt = delete_stmt.where(ProjectRow.organization_id == resolved_organization_id)
                await session.execute(thread_update.values(project_id=None, updated_at=ThreadMetaRow.__table__.c.updated_at))
                result = await session.execute(delete_stmt)
            return result.rowcount > 0


class ProjectDocumentRepository:
    """Project shelf documents: hash-qualified rows with a recoverable trash tier.

    Every read filters ``trashed_at IS NULL`` unless explicitly asked
    otherwise — trashed rows are invisible to the shelf index, the tools, and
    the listing APIs. Writes follow the Phase-1 lock idiom: SQLite takes the
    write lock up front (``BEGIN IMMEDIATE``), Postgres relies on
    ``SELECT … FOR UPDATE`` on the ``projects`` row; existence/ownership/
    status validation happens inside the mutating transaction, never as a
    separate check-then-act read (Phase-2 spec §6.3, §15.5).
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @staticmethod
    def _row_to_dict(row: ProjectDocumentRow) -> dict[str, Any]:
        d = row.to_dict()
        for key in ("created_at", "updated_at", "trashed_at"):
            val = d.get(key)
            if isinstance(val, datetime):
                d[key] = coerce_iso(val)
        return d

    @staticmethod
    async def _begin_immediate_if_sqlite(session: AsyncSession) -> None:
        if session.get_bind().dialect.name == "sqlite":
            # Read-then-write transaction: take the write lock up front
            # (ThreadMetaRepository precedent) so a concurrent writer cannot
            # interleave between the project lock and the mutation.
            await session.execute(text("BEGIN IMMEDIATE"))

    @staticmethod
    async def _lock_active_project(session: AsyncSession, project_id: str, resolved_user_id: str | None, resolved_organization_id: str | None = None) -> ProjectRow | None:
        """Lock the owned ``status='active'`` project row inside the transaction."""
        stmt = select(ProjectRow).where(ProjectRow.id == project_id, ProjectRow.status == "active")
        if resolved_user_id is not None:
            stmt = stmt.where(ProjectRow.user_id == resolved_user_id)
        if resolved_organization_id is not None:
            stmt = stmt.where(ProjectRow.organization_id == resolved_organization_id)
        return (await session.execute(stmt.with_for_update())).scalar_one_or_none()

    async def insert_active(
        self,
        project_id: str,
        *,
        document_id: str,
        name: str,
        relpath: str,
        sha256: str,
        size_bytes: int,
        source_thread_id: str | None = None,
        source_kind: str | None = None,
        source_name: str | None = None,
        place_file: Callable[[], Awaitable[None]] | None = None,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> dict | None:
        """Insert one shelf row under the active-project lock, or return the dedup hit.

        One transaction (§6.3 shelf insert): lock the owned active project row
        (``None`` when missing/foreign/archived), dedup-``SELECT`` among active
        ``(project_id, sha256)`` rows, and on a miss invoke *place_file* — the
        atomic staging→final rename into this document's exclusive namespace —
        **before** the ``INSERT`` (file-before-row, §10.3): a crash leaves an
        unreferenced file the sweep collects, never a visible row without
        bytes. A dedup hit skips placement and returns the existing row — the
        first writer's name and provenance win (§10.9); callers recognize the
        hit by ``row["id"] != document_id``.
        """
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectDocumentRepository.insert_active")
        resolved_organization_id = resolve_organization_id()
        async with self._sf() as session:
            await self._begin_immediate_if_sqlite(session)
            project = await self._lock_active_project(session, project_id, resolved_user_id, resolved_organization_id)
            if project is None:
                await session.rollback()
                return None
            dedup_stmt = select(ProjectDocumentRow).where(
                ProjectDocumentRow.project_id == project_id,
                ProjectDocumentRow.sha256 == sha256,
                ProjectDocumentRow.trashed_at.is_(None),
            )
            if resolved_user_id is not None:
                dedup_stmt = dedup_stmt.where(ProjectDocumentRow.user_id == resolved_user_id)
            if resolved_organization_id is not None:
                dedup_stmt = dedup_stmt.where(ProjectDocumentRow.organization_id == resolved_organization_id)
            existing = (await session.execute(dedup_stmt)).scalars().first()
            if existing is not None:
                await session.commit()
                return self._row_to_dict(existing)
            if place_file is not None:
                # Drained: cancellation waits for the placement worker instead of
                # releasing the project lock over in-flight filesystem work.
                await await_drained(place_file())
            now = datetime.now(UTC)
            row = ProjectDocumentRow(
                id=document_id,
                project_id=project_id,
                user_id=resolved_user_id,
                organization_id=organization_from_owned_parent(project, resolved_user_id, parent_name="project"),
                name=name,
                stored_relpath=relpath,
                sha256=sha256,
                size_bytes=size_bytes,
                source_thread_id=source_thread_id,
                source_kind=source_kind,
                source_name=source_name,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return self._row_to_dict(row)

    async def find_active_by_sha256(self, project_id: str, sha256: str, *, user_id: str | None | _AutoSentinel = AUTO) -> dict | None:
        """Return the active row with this content address, or ``None`` (dedup probe)."""
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectDocumentRepository.find_active_by_sha256")
        resolved_organization_id = resolve_organization_id()
        stmt = select(ProjectDocumentRow).where(
            ProjectDocumentRow.project_id == project_id,
            ProjectDocumentRow.sha256 == sha256,
            ProjectDocumentRow.trashed_at.is_(None),
        )
        if resolved_user_id is not None:
            stmt = stmt.where(ProjectDocumentRow.user_id == resolved_user_id)
        if resolved_organization_id is not None:
            stmt = stmt.where(ProjectDocumentRow.organization_id == resolved_organization_id)
        async with self._sf() as session:
            row = (await session.execute(stmt)).scalars().first()
            return self._row_to_dict(row) if row is not None else None

    async def list_active(self, project_id: str, *, limit: int, offset: int, user_id: str | None | _AutoSentinel = AUTO) -> list[dict]:
        """Active shelf rows in index order: ``updated_at DESC, id ASC`` (§10.10)."""
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectDocumentRepository.list_active")
        resolved_organization_id = resolve_organization_id()
        stmt = select(ProjectDocumentRow).where(ProjectDocumentRow.project_id == project_id, ProjectDocumentRow.trashed_at.is_(None)).order_by(ProjectDocumentRow.updated_at.desc(), ProjectDocumentRow.id.asc()).limit(limit).offset(offset)
        if resolved_user_id is not None:
            stmt = stmt.where(ProjectDocumentRow.user_id == resolved_user_id)
        if resolved_organization_id is not None:
            stmt = stmt.where(ProjectDocumentRow.organization_id == resolved_organization_id)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(r) for r in result.scalars()]

    async def count_active(self, project_id: str, *, user_id: str | None | _AutoSentinel = AUTO) -> int:
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectDocumentRepository.count_active")
        resolved_organization_id = resolve_organization_id()
        stmt = select(func.count()).select_from(ProjectDocumentRow).where(ProjectDocumentRow.project_id == project_id, ProjectDocumentRow.trashed_at.is_(None))
        if resolved_user_id is not None:
            stmt = stmt.where(ProjectDocumentRow.user_id == resolved_user_id)
        if resolved_organization_id is not None:
            stmt = stmt.where(ProjectDocumentRow.organization_id == resolved_organization_id)
        async with self._sf() as session:
            return int((await session.execute(stmt)).scalar_one())

    async def shelf_snapshot(self, project_id: str, *, limit: int, user_id: str | None | _AutoSentinel = AUTO) -> tuple[list[dict], int]:
        """Return ``(rows, total)`` for the pinned shelf index in one round trip.

        ``rows`` are the first ``limit`` active rows in ``updated_at DESC,
        id ASC`` order against the same database snapshot as ``total``; the
        caller (§7.1 step 2) fetches ``shelf_index_max_entries + 1`` and uses
        the extra row only to decide truncation — it is never rendered.
        """
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectDocumentRepository.shelf_snapshot")
        resolved_organization_id = resolve_organization_id()
        stmt = (
            select(ProjectDocumentRow, func.count().over().label("total"))
            .where(ProjectDocumentRow.project_id == project_id, ProjectDocumentRow.trashed_at.is_(None))
            .order_by(ProjectDocumentRow.updated_at.desc(), ProjectDocumentRow.id.asc())
            .limit(limit)
        )
        if resolved_user_id is not None:
            stmt = stmt.where(ProjectDocumentRow.user_id == resolved_user_id)
        if resolved_organization_id is not None:
            stmt = stmt.where(ProjectDocumentRow.organization_id == resolved_organization_id)
        async with self._sf() as session:
            result = await session.execute(stmt)
            pairs = result.all()
            rows = [self._row_to_dict(row) for row, _total in pairs]
            total = int(pairs[0][1]) if pairs else 0
            return rows, total

    async def get(self, document_id: str, *, include_trashed: bool = False, user_id: str | None | _AutoSentinel = AUTO) -> dict | None:
        """Return one owned row, or ``None`` (missing/foreign; trashed unless included)."""
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectDocumentRepository.get")
        resolved_organization_id = resolve_organization_id()
        async with self._sf() as session:
            row = await session.get(ProjectDocumentRow, document_id)
            if row is None:
                return None
            if resolved_user_id is not None and row.user_id != resolved_user_id:
                return None
            if resolved_organization_id is not None and row.organization_id != resolved_organization_id:
                return None
            if row.trashed_at is not None and not include_trashed:
                return None
            return self._row_to_dict(row)

    async def trash(self, document_id: str, *, project_id: str | None = None, user_id: str | None | _AutoSentinel = AUTO) -> bool:
        """Move one owned document to trash; ``False`` ⇒ 404 (§6.3 trash).

        Locks the owned **active** project row first — an archived shelf
        rejects this write (§8.4) — then the owned document row in the same
        transaction, and applies the guarded ``UPDATE … WHERE project_id =
        :pid AND trashed_at IS NULL``. ``False`` covers every failure shape
        (missing/foreign document, missing/foreign/archived project, already
        trashed) so the route never leaks existence.

        *project_id* is the caller's expected project (the route's URL
        project): when given, both the unlocked probe and the locked re-read
        require the row to belong to it — a document of a sibling project is
        indistinguishable from missing, and the guarded ``UPDATE`` predicates
        on the expected id. When omitted, the document's own project is used.
        """
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectDocumentRepository.trash")
        resolved_organization_id = resolve_organization_id()
        async with self._sf() as session:
            await self._begin_immediate_if_sqlite(session)
            # Route to the owning project: the authoritative validation is the
            # locked re-read below, so this unlocked probe leaks nothing.
            probe = await session.get(ProjectDocumentRow, document_id)
            if (
                probe is None
                or (project_id is not None and probe.project_id != project_id)
                or (resolved_user_id is not None and probe.user_id != resolved_user_id)
                or (resolved_organization_id is not None and probe.organization_id != resolved_organization_id)
            ):
                await session.rollback()
                return False
            expected_project_id = project_id if project_id is not None else probe.project_id
            locked_project = await self._lock_active_project(session, expected_project_id, resolved_user_id, resolved_organization_id)
            if locked_project is None:
                await session.rollback()
                return False
            locked = (await session.execute(select(ProjectDocumentRow).where(ProjectDocumentRow.id == document_id).with_for_update())).scalar_one_or_none()
            if (
                locked is None
                or locked.project_id != expected_project_id
                or (resolved_user_id is not None and locked.user_id != resolved_user_id)
                or (resolved_organization_id is not None and locked.organization_id != resolved_organization_id)
            ):
                await session.rollback()
                return False
            stmt = (
                update(ProjectDocumentRow)
                .where(
                    ProjectDocumentRow.id == document_id,
                    ProjectDocumentRow.project_id == expected_project_id,
                    ProjectDocumentRow.trashed_at.is_(None),
                )
                .values(
                    trashed_at=datetime.now(UTC),
                    trash_origin={"project_id": locked_project.id, "project_name": locked_project.name},
                )
            )
            if resolved_user_id is not None:
                stmt = stmt.where(ProjectDocumentRow.user_id == resolved_user_id)
            if resolved_organization_id is not None:
                stmt = stmt.where(ProjectDocumentRow.organization_id == resolved_organization_id)
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount > 0

    @staticmethod
    async def trash_all_for_project(session: AsyncSession, project_id: str, *, project_name: str, user_id: str | None, organization_id: str | None = None) -> int:
        """Trash every active shelf row of a project inside the caller's transaction.

        §8.1 statement 2: runs under the same project row lock
        ``ProjectRepository.delete`` already holds, so a concurrent shelf
        insert either commits first (and is trashed here) or blocks and then
        finds no active project — never an active row pointing at a deleted
        project. No filesystem work: rows snapshot ``{project_id,
        project_name}`` before the project row disappears.
        """
        stmt = (
            update(ProjectDocumentRow)
            .where(ProjectDocumentRow.project_id == project_id, ProjectDocumentRow.trashed_at.is_(None))
            .values(
                trashed_at=datetime.now(UTC),
                trash_origin={"project_id": project_id, "project_name": project_name},
            )
        )
        if user_id is not None:
            stmt = stmt.where(ProjectDocumentRow.user_id == user_id)
        if organization_id is not None:
            stmt = stmt.where(ProjectDocumentRow.organization_id == organization_id)
        result = await session.execute(stmt)
        return int(result.rowcount or 0)

    async def stage_live_copy[T](
        self,
        document_id: str,
        *,
        project_id: str,
        stage: Callable[[dict[str, Any]], Awaitable[T]],
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> tuple[dict[str, Any], T] | None:
        """Run *stage* while holding the owned LIVE document row's lock (§7.3 item 3).

        Attach-to-thread reads a stable source copy serialized against purge
        and trash: this takes the document row lock inside one transaction
        (``BEGIN IMMEDIATE`` on SQLite, ``SELECT … FOR UPDATE`` elsewhere),
        validates ownership, shelf membership and liveness (``trashed_at IS
        NULL`` — an archived source project stays readable, §8.4), then
        invokes *stage* with the row dict and commits. A concurrent purge
        either commits first (the locked re-read finds the row gone/trashed
        and this returns ``None``) or blocks until the copy finishes — never
        a partially copied source. Only the document lock is taken, so no
        lock-ordering hazard exists against purge's project→document order
        (§6.3). The staged copy is the caller's responsibility once the lock
        is released.
        """
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectDocumentRepository.stage_live_copy")
        resolved_organization_id = resolve_organization_id()
        async with self._sf() as session:
            await self._begin_immediate_if_sqlite(session)
            locked = (await session.execute(select(ProjectDocumentRow).where(ProjectDocumentRow.id == document_id).with_for_update())).scalar_one_or_none()
            if (
                locked is None
                or locked.project_id != project_id
                or locked.trashed_at is not None
                or (resolved_user_id is not None and locked.user_id != resolved_user_id)
                or (resolved_organization_id is not None and locked.organization_id != resolved_organization_id)
            ):
                await session.rollback()
                return None
            row = self._row_to_dict(locked)
            # Drained: the lock is never released over an in-flight staging copy.
            staged = await await_drained(stage(row))
            await session.commit()
            return row, staged

    async def convert_under_live_lock[T](
        self,
        document_id: str,
        *,
        project_id: str,
        convert: Callable[[dict[str, Any]], Awaitable[T]],
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> tuple[dict[str, Any], T] | None:
        """Run *convert* while holding the owned LIVE document row's lock (§6.3).

        Lazy conversion publishes ``derived/converted.md`` serialized against
        trash and purge: this takes the document row lock inside one
        transaction (``BEGIN IMMEDIATE`` on SQLite, ``SELECT … FOR UPDATE``
        elsewhere), revalidates ownership, shelf membership and active state
        (``trashed_at IS NULL``) AFTER locking, then invokes *convert* — the
        offloaded convert-to-temp + atomic ``os.replace`` publish — and
        commits. A concurrent trash/purge either commits first (the locked
        re-read finds the row gone/trashed and this returns ``None`` without
        invoking *convert*, so nothing is published) or blocks until the
        publish commits — a derived file is never published after purge
        removed the original (§6.3 lock order, §13). Only the document lock
        is taken, so no lock-ordering hazard exists against trash's
        project→document order. ``None`` means missing/foreign/trashed; the
        caller maps it to its not-on-the-shelf / ``content_missing``
        semantics.
        """
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectDocumentRepository.convert_under_live_lock")
        resolved_organization_id = resolve_organization_id()
        async with self._sf() as session:
            await self._begin_immediate_if_sqlite(session)
            locked = (await session.execute(select(ProjectDocumentRow).where(ProjectDocumentRow.id == document_id).with_for_update())).scalar_one_or_none()
            if (
                locked is None
                or locked.project_id != project_id
                or locked.trashed_at is not None
                or (resolved_user_id is not None and locked.user_id != resolved_user_id)
                or (resolved_organization_id is not None and locked.organization_id != resolved_organization_id)
            ):
                await session.rollback()
                return None
            row = self._row_to_dict(locked)
            # Drained: a cancelled conversion finishes its worker (and any
            # publish) before the document lock unwinds (§6.3).
            result = await await_drained(convert(row))
            await session.commit()
            return row, result

    async def list_trashed(self, *, limit: int, offset: int, user_id: str | None | _AutoSentinel = AUTO) -> list[dict]:
        """Trashed rows, most recently trashed first (trash listing, §6.5)."""
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectDocumentRepository.list_trashed")
        resolved_organization_id = resolve_organization_id()
        stmt = select(ProjectDocumentRow).where(ProjectDocumentRow.trashed_at.is_not(None)).order_by(ProjectDocumentRow.trashed_at.desc(), ProjectDocumentRow.id.asc()).limit(limit).offset(offset)
        if resolved_user_id is not None:
            stmt = stmt.where(ProjectDocumentRow.user_id == resolved_user_id)
        if resolved_organization_id is not None:
            stmt = stmt.where(ProjectDocumentRow.organization_id == resolved_organization_id)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(r) for r in result.scalars()]

    async def count_trashed(self, *, user_id: str | None | _AutoSentinel = AUTO) -> int:
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectDocumentRepository.count_trashed")
        resolved_organization_id = resolve_organization_id()
        stmt = select(func.count()).select_from(ProjectDocumentRow).where(ProjectDocumentRow.trashed_at.is_not(None))
        if resolved_user_id is not None:
            stmt = stmt.where(ProjectDocumentRow.user_id == resolved_user_id)
        if resolved_organization_id is not None:
            stmt = stmt.where(ProjectDocumentRow.organization_id == resolved_organization_id)
        async with self._sf() as session:
            return int((await session.execute(stmt)).scalar_one())

    async def list_all_trashed(self, *, user_id: str | None | _AutoSentinel = AUTO) -> list[dict]:
        """Every trashed row of the caller, oldest first — the Empty-trash pool (§8.3).

        Empty trash removes exactly what the user confirmed, so it selects on
        trashed state alone; ``purge_candidates`` stays the only age-gated
        selection (the retention sweep's).
        """
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectDocumentRepository.list_all_trashed")
        resolved_organization_id = resolve_organization_id()
        stmt = select(ProjectDocumentRow).where(ProjectDocumentRow.trashed_at.is_not(None)).order_by(ProjectDocumentRow.trashed_at.asc(), ProjectDocumentRow.id.asc())
        if resolved_user_id is not None:
            stmt = stmt.where(ProjectDocumentRow.user_id == resolved_user_id)
        if resolved_organization_id is not None:
            stmt = stmt.where(ProjectDocumentRow.organization_id == resolved_organization_id)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(r) for r in result.scalars()]

    async def list_all_for_sweep(self, *, user_id: str | None | _AutoSentinel = AUTO) -> list[dict]:
        """Every row — active and trashed — for retention-sweep reconciliation.

        The sweep (§8.3) needs the full row set of the swept user(s): any row
        protects its entire original/derived namespace from orphan collection
        (even after restore re-pointed it to another project), and row-side
        reconciliation detects missing/size-mismatched content without
        deleting anything.
        """
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectDocumentRepository.list_all_for_sweep")
        resolved_organization_id = resolve_organization_id()
        stmt = select(ProjectDocumentRow).order_by(ProjectDocumentRow.id.asc())
        if resolved_user_id is not None:
            stmt = stmt.where(ProjectDocumentRow.user_id == resolved_user_id)
        if resolved_organization_id is not None:
            stmt = stmt.where(ProjectDocumentRow.organization_id == resolved_organization_id)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(r) for r in result.scalars()]

    async def restore(
        self,
        document_id: str,
        *,
        target_project_id: str,
        check_content: Callable[[dict[str, Any]], Awaitable[bool]] | None = None,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> tuple[Literal["restored", "merged", "not_found", "no_target", "content_missing"], dict | None]:
        """Restore one trashed row into an active target project (§6.3/§8.2).

        One transaction: lock the target active owned project row first
        (``None`` ⇒ ``no_target``: missing/foreign/archived are
        indistinguishable), then lock the source and any merge-candidate rows
        in ID order. Source ownership and ``trashed_at IS NOT NULL`` are
        revalidated after locking (missing/already-restored/purged ⇒
        ``not_found``). Before either outcome, *check_content* verifies the
        original's existence/size under the source lock — and, for a merge,
        the surviving target's content under its lock; a failure yields
        ``content_missing`` and leaves the source trashed (§8.3). Merge: the
        target already has an active row with the same ``sha256``, so the
        trash row is deleted and the surviving row returned; the caller
        unlinks the discarded source namespace best-effort AFTER commit.
        Otherwise the row is re-pointed (``project_id`` = target, trash
        fields cleared, ``organization_id`` re-derived from the target) with
        NO file moves — ``stored_relpath`` is projects-root-relative, so the
        bytes stay valid (§10.6).

        The source lookup below intentionally checks only ``user_id``, never
        ``organization_id``: ``user_id`` (the storage principal) already
        proves ownership on this table, and restore is the row's one
        healing opportunity for a stale/NULL ``organization_id`` (a legacy
        row, or a prior restore that predates this fix) — gating the lookup
        on a match would make such a row permanently unrestorable instead of
        healed.
        """
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectDocumentRepository.restore")
        resolved_organization_id = resolve_organization_id()
        async with self._sf() as session:
            await self._begin_immediate_if_sqlite(session)
            locked_project = await self._lock_active_project(session, target_project_id, resolved_user_id, resolved_organization_id)
            if locked_project is None:
                await session.rollback()
                return "no_target", None
            # Identify the source and any merge candidates before locking.
            # This unlocked probe only chooses WHICH rows to lock; every
            # validation below re-reads the locked rows.
            probe = (await session.execute(select(ProjectDocumentRow.id, ProjectDocumentRow.sha256, ProjectDocumentRow.trashed_at).where(ProjectDocumentRow.id == document_id))).first()
            if probe is None:
                await session.rollback()
                return "not_found", None
            lock_ids = [document_id]
            if probe.trashed_at is not None:
                candidates = await session.execute(
                    select(ProjectDocumentRow.id).where(
                        ProjectDocumentRow.project_id == target_project_id,
                        ProjectDocumentRow.sha256 == probe.sha256,
                        ProjectDocumentRow.trashed_at.is_(None),
                        ProjectDocumentRow.id != document_id,
                    )
                )
                lock_ids.extend(row[0] for row in candidates.all())
            locked_rows = (await session.execute(select(ProjectDocumentRow).where(ProjectDocumentRow.id.in_(lock_ids)).order_by(ProjectDocumentRow.id.asc()).with_for_update())).scalars().all()
            by_id = {row.id: row for row in locked_rows}
            source = by_id.get(document_id)
            # Revalidate under the lock: ownership + still trashed. See the
            # docstring above for why this is user_id-only.
            if source is None or source.trashed_at is None or (resolved_user_id is not None and source.user_id != resolved_user_id):
                await session.rollback()
                return "not_found", None
            if check_content is not None and not await await_drained(check_content(self._row_to_dict(source))):
                # Missing/size-mismatched bytes: leave the row trashed (§8.3).
                await session.rollback()
                return "content_missing", None
            surviving = next(
                (row for row in locked_rows if row.id != document_id and row.project_id == target_project_id and row.sha256 == source.sha256 and row.trashed_at is None and (resolved_user_id is None or row.user_id == resolved_user_id)),
                None,
            )
            if surviving is not None:
                if check_content is not None and not await await_drained(check_content(self._row_to_dict(surviving))):
                    await session.rollback()
                    return "content_missing", None
                # Merge: the target already serves these bytes; delete the
                # trash row (guarded) and report the surviving row. No file
                # mutation inside the transaction — the discarded namespace
                # cleanup follows commit (§8.2).
                result = await session.execute(sa_delete(ProjectDocumentRow).where(ProjectDocumentRow.id == document_id, ProjectDocumentRow.trashed_at.is_not(None)))
                await session.commit()
                if result.rowcount == 0:
                    return "not_found", None
                return "merged", self._row_to_dict(surviving)
            # Re-point: no file moves (§10.6). The document row lock held
            # since the revalidation above serializes this against purge.
            # organization_id is re-derived from the now-locked target
            # project, exactly like insert_active's stamp — never left as
            # whatever the source row carried (the bug this fixes: a stale
            # or NULL organization_id survived a restore untouched).
            source.project_id = target_project_id
            source.organization_id = organization_from_owned_parent(locked_project, resolved_user_id, parent_name="project")
            source.trashed_at = None
            source.trash_origin = None
            await session.commit()
            await session.refresh(source)
            return "restored", self._row_to_dict(source)

    async def purge_candidates(self, retention_days: int, *, now: datetime | None = None, user_id: str | None | _AutoSentinel = AUTO) -> list[dict]:
        """Trashed rows at or past the retention window, oldest first (§8.3).

        A row trashed exactly ``retention_days`` ago is eligible — the window
        has fully passed. The sweep revalidates each candidate's trash
        timestamp and the cutoff under the purge lock before removing
        anything (§6.1).
        """
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectDocumentRepository.purge_candidates")
        resolved_organization_id = resolve_organization_id()
        cutoff = (now or datetime.now(UTC)) - timedelta(days=retention_days)
        stmt = select(ProjectDocumentRow).where(ProjectDocumentRow.trashed_at.is_not(None), ProjectDocumentRow.trashed_at <= cutoff).order_by(ProjectDocumentRow.trashed_at.asc(), ProjectDocumentRow.id.asc())
        if resolved_user_id is not None:
            stmt = stmt.where(ProjectDocumentRow.user_id == resolved_user_id)
        if resolved_organization_id is not None:
            stmt = stmt.where(ProjectDocumentRow.organization_id == resolved_organization_id)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(r) for r in result.scalars()]

    async def purge(
        self,
        document_id: str,
        *,
        retention_cutoff: datetime | None = None,
        expected_trashed_at: datetime | str | None = None,
        remove_files: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> bool:
        """Permanently delete one trashed row and its bytes (§6.3/§8.3).

        One database transaction holds the owned document-row lock
        continuously across trashed-state revalidation, *remove_files*
        (unlink of the original and ``derived/converted.md``), row deletion
        and commit — restore cannot pass its source-row lock meanwhile.
        Purge acquires only its document lock and never later waits on a
        project lock (§6.3 lock order). Retention callers pass
        ``expected_trashed_at`` + ``retention_cutoff`` from their candidate
        selection; both are revalidated under the lock, so a row restored
        and later re-trashed is NOT purged on its former expiry. Manual
        purge passes neither and only requires the row to be trashed now.
        ``FileNotFoundError`` inside *remove_files* counts as already
        removed; any other error rolls the transaction back and leaves a
        retryable trashed row. ``False`` ⇒ 404 (missing, foreign, not
        trashed, or no longer matching the retention selection). No public
        unguarded row deletion exists.
        """
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectDocumentRepository.purge")
        resolved_organization_id = resolve_organization_id()
        async with self._sf() as session:
            await self._begin_immediate_if_sqlite(session)
            lock_stmt = select(ProjectDocumentRow).where(ProjectDocumentRow.id == document_id)
            if resolved_user_id is not None:
                lock_stmt = lock_stmt.where(ProjectDocumentRow.user_id == resolved_user_id)
            if resolved_organization_id is not None:
                lock_stmt = lock_stmt.where(ProjectDocumentRow.organization_id == resolved_organization_id)
            locked = (await session.execute(lock_stmt.with_for_update())).scalar_one_or_none()
            if locked is None or locked.trashed_at is None:
                await session.rollback()
                return False
            if expected_trashed_at is not None and coerce_iso(locked.trashed_at) != coerce_iso(expected_trashed_at):
                # Restored and re-trashed since candidate selection: the
                # former expiry no longer applies (§6.1).
                await session.rollback()
                return False
            if retention_cutoff is not None:
                trashed_at = locked.trashed_at
                if trashed_at.tzinfo is None:
                    trashed_at = trashed_at.replace(tzinfo=UTC)
                if trashed_at > retention_cutoff:
                    await session.rollback()
                    return False
            if remove_files is not None:
                try:
                    # Drained: cancellation waits for the unlink worker, so the
                    # row lock is released only after the filesystem work finished.
                    await await_drained(remove_files(self._row_to_dict(locked)))
                except Exception:
                    # Filesystem work is not rollbackable, but the row is:
                    # keep the trashed row so the purge stays retryable (§8.3).
                    await session.rollback()
                    raise
            result = await session.execute(sa_delete(ProjectDocumentRow).where(ProjectDocumentRow.id == document_id, ProjectDocumentRow.trashed_at.is_not(None)))
            await session.commit()
            return result.rowcount > 0
````

## frontend/src/core/projects/api.ts

````typescript
import { fetch as fetchWithAuth } from "@/core/api/fetcher";
import {
  ARTIFACT_PREVIEW_MAX_BYTES,
  parseContentRange,
} from "@/core/artifacts/loader";
import { getBackendBaseURL } from "@/core/config";

import type {
  AttachProjectDocumentResult,
  Project,
  ProjectCreateInput,
  ProjectDocument,
  ProjectPatchInput,
  ProjectStatus,
  ProjectThread,
  ProjectThreadFileGroup,
  PromoteThreadFileInput,
} from "./types";

export type ProjectListResponse = {
  projects: Project[];
};

/** ``GET /api/projects/{id}/documents`` envelope (spec §6.5). */
export type ProjectDocumentListResponse = {
  documents: ProjectDocument[];
  total: number;
  limit: number;
  offset: number;
};

/**
 * Upload/promote response: ``deduplicated`` distinguishes the 200 dedup hit
 * (existing row, first name wins, §10.9) from the 201 created row.
 */
export type ProjectDocumentUploadResponse = {
  document: ProjectDocument;
  deduplicated: boolean;
};

/** ``GET /api/projects/{id}/thread-files`` envelope (spec §7.4). */
export type ProjectThreadFilesResponse = {
  groups: ProjectThreadFileGroup[];
  next_offset: number | null;
  truncated: boolean;
};

export const PROJECTS_QUERY_KEY = ["projects"] as const;

/** ``GET /api/projects/config`` payload (spec §6.5). */
export type ProjectsConfig = {
  instructions_max_bytes: number;
  trash_retention_days: number;
};

/**
 * Client mirror of the server defaults (config/projects_config.py): callers
 * fall back to these when the config endpoint is unavailable (older gateway,
 * network failure), matching what an unconfigured server enforces.
 */
export const PROJECTS_CONFIG_DEFAULT: ProjectsConfig = {
  instructions_max_bytes: 8192,
  trash_retention_days: 30,
};

/** Server-configured projects limits; shared by the editor and trash. */
export async function getProjectsConfig(): Promise<ProjectsConfig> {
  const response = await fetchWithAuth(
    `${getBackendBaseURL()}/api/projects/config`,
    {
      method: "GET",
    },
  );

  if (!response.ok) {
    throw new Error(
      await readProjectAPIError(response, "Failed to load projects config."),
    );
  }

  return (await response.json()) as ProjectsConfig;
}

async function readProjectAPIError(
  response: Response,
  fallback: string,
): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string" && body.detail) {
      return body.detail;
    }
  } catch {
    // Fall through to the caller-provided message.
  }
  return fallback;
}

function projectUrl(projectId: string, suffix = ""): string {
  return `${getBackendBaseURL()}/api/projects/${encodeURIComponent(projectId)}${suffix}`;
}

export async function listProjects(
  status?: ProjectStatus,
  options: { signal?: AbortSignal } = {},
): Promise<Project[]> {
  const response = await fetchWithAuth(
    `${getBackendBaseURL()}/api/projects${status ? `?status=${encodeURIComponent(status)}` : ""}`,
    {
      method: "GET",
      signal: options.signal,
      cache: "no-store",
    },
  );

  if (!response.ok) {
    throw new Error(
      await readProjectAPIError(response, "Failed to load projects."),
    );
  }

  const body = (await response.json()) as ProjectListResponse;
  return body.projects;
}

export async function getProject(projectId: string): Promise<Project> {
  const response = await fetchWithAuth(projectUrl(projectId), {
    method: "GET",
  });

  if (!response.ok) {
    throw new Error(
      await readProjectAPIError(response, "Failed to load project."),
    );
  }

  return (await response.json()) as Project;
}

export async function createProject(
  input: ProjectCreateInput,
): Promise<Project> {
  const response = await fetchWithAuth(`${getBackendBaseURL()}/api/projects`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      name: input.name,
      instructions: input.instructions ?? "",
      presentation: input.presentation ?? {},
    }),
  });

  if (!response.ok) {
    throw new Error(
      await readProjectAPIError(response, "Failed to create project."),
    );
  }

  return (await response.json()) as Project;
}

export async function patchProject(
  projectId: string,
  input: ProjectPatchInput,
): Promise<Project> {
  const response = await fetchWithAuth(projectUrl(projectId), {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      ...(input.name !== undefined ? { name: input.name } : {}),
      ...(input.instructions !== undefined
        ? { instructions: input.instructions }
        : {}),
      ...(input.presentation !== undefined
        ? { presentation: input.presentation }
        : {}),
    }),
  });

  if (!response.ok) {
    throw new Error(
      await readProjectAPIError(response, "Failed to update project."),
    );
  }

  return (await response.json()) as Project;
}

export async function archiveProject(projectId: string): Promise<Project> {
  const response = await fetchWithAuth(projectUrl(projectId, "/archive"), {
    method: "POST",
  });

  if (!response.ok) {
    throw new Error(
      await readProjectAPIError(response, "Failed to archive project."),
    );
  }

  return (await response.json()) as Project;
}

export async function restoreProject(projectId: string): Promise<Project> {
  const response = await fetchWithAuth(projectUrl(projectId, "/restore"), {
    method: "POST",
  });

  if (!response.ok) {
    throw new Error(
      await readProjectAPIError(response, "Failed to restore project."),
    );
  }

  return (await response.json()) as Project;
}

export async function deleteProject(projectId: string): Promise<void> {
  const response = await fetchWithAuth(projectUrl(projectId), {
    method: "DELETE",
  });

  if (!response.ok) {
    throw new Error(
      await readProjectAPIError(response, "Failed to delete project."),
    );
  }
}

export async function listProjectThreads(
  projectId: string,
  params: { limit?: number; offset?: number } = {},
): Promise<ProjectThread[]> {
  const search = new URLSearchParams();
  if (params.limit !== undefined) {
    search.set("limit", String(params.limit));
  }
  if (params.offset !== undefined) {
    search.set("offset", String(params.offset));
  }
  const query = search.size > 0 ? `?${search.toString()}` : "";
  const response = await fetchWithAuth(
    projectUrl(projectId, `/threads${query}`),
    {
      method: "GET",
    },
  );

  if (!response.ok) {
    throw new Error(
      await readProjectAPIError(response, "Failed to load project threads."),
    );
  }

  return (await response.json()) as ProjectThread[];
}

export async function listProjectDocuments(
  projectId: string,
  params: { limit?: number; offset?: number } = {},
): Promise<ProjectDocumentListResponse> {
  const search = new URLSearchParams();
  if (params.limit !== undefined) {
    search.set("limit", String(params.limit));
  }
  if (params.offset !== undefined) {
    search.set("offset", String(params.offset));
  }
  const query = search.size > 0 ? `?${search.toString()}` : "";
  const response = await fetchWithAuth(
    projectUrl(projectId, `/documents${query}`),
    {
      method: "GET",
    },
  );

  if (!response.ok) {
    throw new Error(
      await readProjectAPIError(response, "Failed to load project documents."),
    );
  }

  return (await response.json()) as ProjectDocumentListResponse;
}

/**
 * Shelf exactly one file per request (spec §17.2); the UI loops for
 * multi-file drops. 201 created and 200 dedup hit are both success.
 */
export async function uploadProjectDocument(
  projectId: string,
  { file, name }: { file: File; name?: string },
): Promise<ProjectDocumentUploadResponse> {
  const formData = new FormData();
  formData.append("file", file);
  if (name !== undefined) {
    formData.append("name", name);
  }
  const response = await fetchWithAuth(projectUrl(projectId, "/documents"), {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    throw new Error(
      await readProjectAPIError(response, "Failed to upload project document."),
    );
  }

  return (await response.json()) as ProjectDocumentUploadResponse;
}

/** Save a thread file (upload or output) onto the project shelf (spec §7.4). */
export async function promoteThreadFile(
  projectId: string,
  input: PromoteThreadFileInput,
): Promise<ProjectDocumentUploadResponse> {
  const response = await fetchWithAuth(
    projectUrl(projectId, "/documents/from-thread"),
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        thread_id: input.thread_id,
        kind: input.kind,
        name: input.name,
        ...(input.shelf_name !== undefined
          ? { shelf_name: input.shelf_name }
          : {}),
      }),
    },
  );

  if (!response.ok) {
    throw new Error(
      await readProjectAPIError(response, "Failed to save file to project."),
    );
  }

  return (await response.json()) as ProjectDocumentUploadResponse;
}

/** Attach a shelf document into a thread through the uploads path (§7.3). */
export async function attachProjectDocument(
  projectId: string,
  documentId: string,
  threadId: string,
): Promise<AttachProjectDocumentResult> {
  const response = await fetchWithAuth(
    projectUrl(
      projectId,
      `/documents/${encodeURIComponent(documentId)}/attach-to-thread/${encodeURIComponent(threadId)}`,
    ),
    {
      method: "POST",
    },
  );

  if (!response.ok) {
    throw new Error(
      await readProjectAPIError(
        response,
        "Failed to attach document to thread.",
      ),
    );
  }

  return (await response.json()) as AttachProjectDocumentResult;
}

/** Move one shelf document to trash (204; restore/purge are the trash tier). */
export async function deleteProjectDocument(
  projectId: string,
  documentId: string,
): Promise<void> {
  const response = await fetchWithAuth(
    projectUrl(projectId, `/documents/${encodeURIComponent(documentId)}`),
    {
      method: "DELETE",
    },
  );

  if (!response.ok) {
    throw new Error(
      await readProjectAPIError(response, "Failed to delete project document."),
    );
  }
}

/**
 * Content endpoint address (spec §6.5): inline text by default, forced
 * attachment with ``download`` — used for the shelf row's download action.
 */
export function urlOfProjectDocumentContent(
  projectId: string,
  documentId: string,
  { download = false }: { download?: boolean } = {},
): string {
  const suffix = `/documents/${encodeURIComponent(documentId)}/content${download ? "?download=true" : ""}`;
  return projectUrl(projectId, suffix);
}

/**
 * Content-missing conflict (HTTP 409 ``content_missing``, spec §11): the
 * row's bytes are gone or damaged, so the page renders the row as
 * content-missing with move-to-trash as its only action.
 */
export class ProjectDocumentContentMissingError extends Error {
  constructor() {
    super("content_missing");
    this.name = "ProjectDocumentContentMissingError";
  }
}

/** Media types the preview dialog decodes as text (bounded prefix only). */
function isTextPreviewMediaType(contentType: string): boolean {
  return (
    contentType.startsWith("text/") ||
    contentType === "application/json" ||
    contentType === "application/xml" ||
    contentType === "application/javascript" ||
    contentType === "application/x-yaml" ||
    contentType === "application/yaml"
  );
}

/**
 * Active-content media types — mirror of the backend's
 * ``deerflow.utils.text_detection._is_active_content_mime_type``: any
 * WHATWG XML type (plus ``text/html``/``text/xsl``) can carry script, so the
 * content endpoint always serves them as an attachment. The preview must
 * never navigate its sandboxed iframe to one (the empty sandbox blocks the
 * download and renders a blank frame).
 */
const ACTIVE_CONTENT_MEDIA_TYPES = new Set([
  "text/html",
  "application/xhtml+xml",
  "image/svg+xml",
  "text/xml",
  "application/xml",
  "text/xsl",
]);

function isActiveContentMediaType(contentType: string): boolean {
  return (
    ACTIVE_CONTENT_MEDIA_TYPES.has(contentType) || contentType.endsWith("+xml")
  );
}

/**
 * Media types the browser renders inline inside the sandboxed iframe —
 * passive binaries only; the active-content XML family (SVG included) is
 * excluded because the endpoint serves it as an attachment. PDF is handled
 * separately (its own preview kind): Chromium blocks the built-in PDF
 * viewer inside ``sandbox=""``, so PDFs render in an unsandboxed iframe.
 */
function isBrowserViewableMediaType(contentType: string): boolean {
  if (isActiveContentMediaType(contentType)) {
    return false;
  }
  return (
    contentType.startsWith("image/") ||
    contentType.startsWith("audio/") ||
    contentType.startsWith("video/")
  );
}

/**
 * Preview payload for the shelf preview dialog (§6.5). Binary documents are
 * never text-decoded: browser-viewable kinds render the content URL in a
 * sandboxed iframe, PDFs render in an iframe WITHOUT the sandbox attribute
 * (Chromium blocks its built-in viewer inside ``sandbox=""``), everything
 * else gets an explicit download fallback.
 */
export type ProjectDocumentPreview =
  | {
      kind: "text";
      content: string;
      truncated: boolean;
      previewBytes: number;
      totalBytes: number | undefined;
    }
  | { kind: "binary" }
  | { kind: "pdf" }
  | { kind: "unsupported" };
/**
 * Fetch a shelf document for the preview dialog (§6.5). The request asks for
 * at most the first ``ARTIFACT_PREVIEW_MAX_BYTES`` through an HTTP byte range
 * (the content endpoint is a Starlette ``FileResponse``, which answers 206);
 * an oversized ``Content-Length`` on a 200 still marks the preview truncated
 * so the dialog offers the explicit full-file action instead of rendering a
 * partial file as complete. The response media type is inspected before any
 * decode: only textual types are decoded, never binary bytes.
 */
export async function fetchProjectDocumentPreview(
  projectId: string,
  documentId: string,
): Promise<ProjectDocumentPreview> {
  const response = await fetchWithAuth(
    urlOfProjectDocumentContent(projectId, documentId),
    {
      headers: { Range: `bytes=0-${ARTIFACT_PREVIEW_MAX_BYTES - 1}` },
    },
  );
  if (response.status === 409) {
    throw new ProjectDocumentContentMissingError();
  }
  const contentRange = parseContentRange(response.headers.get("Content-Range"));
  if (response.status === 416 && contentRange?.total === 0) {
    return {
      kind: "text",
      content: "",
      truncated: false,
      previewBytes: 0,
      totalBytes: 0,
    };
  }
  if (!response.ok) {
    throw new Error(
      await readProjectAPIError(response, "Failed to load document content."),
    );
  }

  const contentType = (response.headers.get("Content-Type") ?? "")
    .split(";")[0]!
    .trim()
    .toLowerCase();
  if (contentType === "application/pdf") {
    // PDFs get their own kind: the dialog renders them in an iframe WITHOUT
    // the sandbox attribute (Chromium blocks its built-in viewer inside
    // ``sandbox=""``), unlike other viewable binaries. The bounded prefix is
    // useless either way — release the body instead of decoding it.
    await response.body?.cancel();
    return { kind: "pdf" };
  }
  if (isBrowserViewableMediaType(contentType)) {
    // The bounded prefix is useless to the iframe, which loads the content
    // URL itself; release the body instead of decoding it.
    await response.body?.cancel();
    return { kind: "binary" };
  }
  if (!isTextPreviewMediaType(contentType)) {
    await response.body?.cancel();
    return { kind: "unsupported" };
  }

  const bytes = await response.arrayBuffer();
  const contentLengthHeader = response.headers.get("Content-Length");
  const contentLength =
    contentLengthHeader === null ? undefined : Number(contentLengthHeader);
  const totalBytes =
    contentRange?.total ??
    (contentLength !== undefined && Number.isFinite(contentLength)
      ? contentLength
      : undefined);
  const previewBytes = Math.min(bytes.byteLength, ARTIFACT_PREVIEW_MAX_BYTES);
  const truncated =
    (response.status === 206 &&
      (contentRange?.end === undefined ||
        contentRange.total > contentRange.end + 1)) ||
    bytes.byteLength > ARTIFACT_PREVIEW_MAX_BYTES ||
    (totalBytes !== undefined &&
      totalBytes > ARTIFACT_PREVIEW_MAX_BYTES &&
      totalBytes > bytes.byteLength);
  // Streaming decode intentionally holds an incomplete trailing UTF-8 code
  // point instead of fabricating U+FFFD at the range boundary.
  const content = new TextDecoder().decode(
    bytes.byteLength > ARTIFACT_PREVIEW_MAX_BYTES
      ? bytes.slice(0, ARTIFACT_PREVIEW_MAX_BYTES)
      : bytes,
    { stream: truncated },
  );
  return { kind: "text", content, truncated, previewBytes, totalBytes };
}

/** Read-only conversation-files view over member threads (spec §7.4). */
export async function listProjectThreadFiles(
  projectId: string,
  params: {
    offset?: number;
    thread_limit?: number;
    file_limit?: number;
  } = {},
): Promise<ProjectThreadFilesResponse> {
  const search = new URLSearchParams();
  if (params.offset !== undefined) {
    search.set("offset", String(params.offset));
  }
  if (params.thread_limit !== undefined) {
    search.set("thread_limit", String(params.thread_limit));
  }
  if (params.file_limit !== undefined) {
    search.set("file_limit", String(params.file_limit));
  }
  const query = search.size > 0 ? `?${search.toString()}` : "";
  const response = await fetchWithAuth(
    projectUrl(projectId, `/thread-files${query}`),
    {
      method: "GET",
    },
  );

  if (!response.ok) {
    throw new Error(
      await readProjectAPIError(response, "Failed to load thread files."),
    );
  }

  return (await response.json()) as ProjectThreadFilesResponse;
}
````

## frontend/src/core/workspaces/hooks.ts

````typescript
import { useIsMutating, useMutation, useQuery } from "@tanstack/react-query";

import { fetch } from "@/core/api/fetcher";

type WorkspaceList = {
  workspaces: { id: string; name: string; role: string }[];
  active_workspace_id: string | null;
  private_workspace_name?: string | null;
};

export function useWorkspaceSelection() {
  const query = useQuery({
    queryKey: ["workspaces"],
    queryFn: async ({ signal }): Promise<WorkspaceList> => {
      const response = await fetch("/api/workspaces", { signal });
      if (!response.ok) throw new Error("Workspace list unavailable");
      return response.json() as Promise<WorkspaceList>;
    },
  });
  const busy = useIsMutating({ mutationKey: ["workspace-selection"] }) > 0;
  const selection = useMutation({
    mutationKey: ["workspace-selection"],
    mutationFn: async (workspaceId: string | null) => {
      const response = await fetch("/api/workspaces/select", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workspace_id: workspaceId }),
      });
      if (!response.ok) {
        throw new Error("Couldn't switch workspace. Refresh and try again.");
      }
      // Discard cached data from the previous workspace before showing chats.
      window.location.assign("/workspace/chats");
    },
  });
  return {
    data: query.data,
    isLoading: query.isLoading,
    busy,
    error: selection.error ?? query.error,
    selectWorkspace: selection.mutateAsync,
  };
}
````

## frontend/src/components/query-client-provider.tsx

````typescript
"use client";

import {
  QueryClient,
  QueryClientProvider as TanStackQueryClientProvider,
} from "@tanstack/react-query";

// One client per browser tab. Exported so logout can drop every cached
// response: a soft navigation keeps this module alive, and the next person
// to sign in on the same tab must not see the previous user's data.
export const queryClient = new QueryClient();

export function QueryClientProvider({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <TanStackQueryClientProvider client={queryClient}>
      {children}
    </TanStackQueryClientProvider>
  );
}
````

## frontend/src/core/auth/AuthProvider.tsx

````typescript
"use client";

import { useRouter, usePathname } from "next/navigation";
import React, {
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  type ReactNode,
} from "react";

import { queryClient } from "@/components/query-client-provider";
import { redirectOnUnauthorized, setLoggingOut } from "@/core/api/fetcher";

import { isStaticWebsiteOnly } from "../static-mode";

import { isClientUser, isRoleUnresolved } from "./roles";
import { type User, buildLoginUrl, userSchema } from "./types";

// Re-export for consumers
export type { User };

/**
 * Authentication context provided to consuming components
 */
interface AuthContextType {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  isLoggingOut: boolean;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
  applyUser: (user: User | null) => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

const useIsomorphicLayoutEffect =
  typeof window === "undefined" ? useEffect : useLayoutEffect;

interface AuthProviderProps {
  children: ReactNode;
  initialUser: User | null;
}

/**
 * AuthProvider - Unified authentication context for the application
 *
 * Per RFC-001:
 * - Only holds display information (user), never JWT or tokens
 * - initialUser comes from server-side guard, avoiding client flicker
 * - Provides logout and refresh capabilities
 */
export function AuthProvider({ children, initialUser }: AuthProviderProps) {
  const [user, setUser] = useState<User | null>(initialUser);
  const [isLoading, setIsLoading] = useState(false);
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const logoutStartedRef = useRef(false);
  const currentUserRef = useRef(initialUser);
  const initialUserRef = useRef(initialUser);
  const authGenerationRef = useRef(0);
  const refreshRequestIdRef = useRef(0);
  const router = useRouter();
  const staticMode = isStaticWebsiteOnly();

  const isAuthenticated = user !== null;

  useIsomorphicLayoutEffect(() => {
    setLoggingOut(false);
  }, []);

  const invalidateAuthRequests = useCallback(() => {
    authGenerationRef.current += 1;
    refreshRequestIdRef.current += 1;
  }, []);

  /**
   * Apply a confirmed user, fencing older refreshes. A different signed-in
   * account reloads the page to discard its observers and cached data together.
   */
  const applyUser = useCallback(
    (next: User | null) => {
      if (logoutStartedRef.current) return;
      // Callers such as the offline banner already hold an authoritative user
      // response. Fence any older /auth/me request before applying it.
      invalidateAuthRequests();
      if (
        currentUserRef.current &&
        next &&
        currentUserRef.current.id !== next.id
      ) {
        setIsLoading(true);
        window.location.reload();
        return;
      }
      currentUserRef.current = next;
      setUser(next);
      setIsLoading(false);
    },
    [invalidateAuthRequests],
  );

  // Layout sync keeps a newly server-confirmed identity from being hidden by
  // the provider's initial useState value during client-side route updates.
  // It also fences a refresh started under the previous server identity.
  useIsomorphicLayoutEffect(() => {
    if (initialUserRef.current === initialUser) return;
    initialUserRef.current = initialUser;
    applyUser(initialUser);
  }, [initialUser, applyUser]);

  /**
   * Fetch current user from FastAPI
   * Used when initialUser might be stale (e.g., after tab was inactive)
   */
  const refreshUser = useCallback(async () => {
    if (staticMode || logoutStartedRef.current) return;

    const requestId = ++refreshRequestIdRef.current;
    const authGeneration = authGenerationRef.current;
    const isCurrentRequest = () =>
      refreshRequestIdRef.current === requestId &&
      authGenerationRef.current === authGeneration;

    try {
      setIsLoading(true);
      const res = await fetch("/api/v1/auth/me", {
        credentials: "include",
      });

      if (res.ok) {
        const parsed = userSchema.safeParse(await res.json());
        if (isCurrentRequest()) {
          if (parsed.success) {
            applyUser(parsed.data);
          } else {
            console.warn("Failed to refresh user: invalid /auth/me response");
          }
        }
      } else if (res.status === 401) {
        // Session expired or invalid
        if (isCurrentRequest()) {
          applyUser(null);
          redirectOnUnauthorized(res);
        }
      }
    } catch (err) {
      // A transport or parse failure does not establish that the session is
      // invalid. Keep the last confirmed user; only a 401 clears it.
      if (isCurrentRequest()) {
        console.error("Failed to refresh user:", err);
      }
    } finally {
      if (isCurrentRequest()) {
        setIsLoading(false);
      }
    }
  }, [staticMode, applyUser]);

  /**
   * Logout - call FastAPI logout endpoint and clear local state
   * Per RFC-001: Immediately clear local state, don't wait for server confirmation
   *
   * When the gateway is unreachable the fetch silently fails — the SPA
   * router.push("/") would leave the user on "/" still holding stale
   * React state and any in-flight SSE / fetch / query subscriptions.
   * We therefore fall back to a hard navigation (window.location.href),
   * which discards all client state the same way the legacy form-POST
   * logout used to.
   */
  const logout = useCallback(async () => {
    // Fence recovery without rebuilding mounted queries under a live session.
    // The workspace/auth layout's provider unmounts on navigation to home.
    logoutStartedRef.current = true;
    setLoggingOut(true);
    invalidateAuthRequests();
    currentUserRef.current = null;
    setUser(null);
    setIsLoading(false);
    setIsLoggingOut(true);

    if (staticMode) {
      queryClient.clear();
      router.push("/");
      return;
    }

    let logoutFailed = false;
    try {
      const res = await fetch("/api/v1/auth/logout", {
        method: "POST",
        credentials: "include",
      });
      if (!res.ok) logoutFailed = true;
    } catch (err) {
      console.error("Logout request failed:", err);
      logoutFailed = true;
    }

    if (logoutFailed && typeof window !== "undefined") {
      // Hard navigation ensures every in-flight subscription is torn down,
      // matching the legacy form-POST logout behaviour during a gateway outage.
      window.location.href = "/";
      return;
    }

    // Drop every cached response (staff-only Team and Academy data among
    // them) before the soft navigation keeps this tab's query cache alive.
    queryClient.clear();
    // Redirect to home page
    router.push("/");
  }, [staticMode, router, invalidateAuthRequests]);

  /**
   * Handle visibility change - refresh user when tab becomes visible again.
   * Throttled to at most once per 60 s to avoid spamming the backend on rapid tab switches.
   */
  const lastCheckRef = React.useRef(0);

  useEffect(() => {
    if (staticMode) return;

    const handleVisibilityChange = () => {
      if (document.visibilityState !== "visible" || user === null) return;
      const now = Date.now();
      if (now - lastCheckRef.current < 60_000) return;
      lastCheckRef.current = now;
      void refreshUser();
    };

    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [staticMode, user, refreshUser]);

  const value: AuthContextType = {
    user,
    isAuthenticated,
    isLoading,
    isLoggingOut,
    logout,
    refreshUser,
    applyUser,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

/**
 * Hook to access authentication context
 * Throws if used outside AuthProvider - this is intentional for proper usage
 */
export function useAuth(): AuthContextType {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}

/** Whether the signed-in user is an external client (chat with MomoBot Max only). */
export function useIsClient(): boolean {
  return isClientUser(useAuth().user);
}

/**
 * Whether the role is still unknown. Treat it as "maybe a client": render
 * nothing internal until it resolves.
 */
export function useIsRoleUnresolved(): boolean {
  return isRoleUnresolved(useAuth().user, isStaticWebsiteOnly());
}

/**
 * Hook to require authentication - redirects to login if not authenticated
 * Useful for client-side checks in addition to server-side guards
 */
export function useRequireAuth(): AuthContextType {
  const auth = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (isStaticWebsiteOnly()) return;

    // Only redirect if we're sure user is not authenticated (not just loading)
    if (!auth.isLoading && !auth.isAuthenticated) {
      router.push(buildLoginUrl(pathname || "/workspace"));
    }
  }, [auth.isAuthenticated, auth.isLoading, router, pathname]);

  return auth;
}
````

## backend/app/gateway/routers/project_documents.py

````python
"""Project document shelf API (Projects Phase 2 Slice B).

Routes under ``/api/projects/{project_id}/documents``: upload one file,
list the shelf, read/download a document's content, and move a document to
trash. Trashed rows are invisible to every endpoint. Fail closed everywhere:
a missing or foreign project/document is a 404 (never a 403 that leaks
existence), an archived project rejects uploads and individual trash with the
same 404 (§8.4), and a memory-backend deployment answers 503 ``"Projects"``
through the shared ``_require`` accessor convention (§11).
"""

from __future__ import annotations

import logging
import mimetypes
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.gateway.authz import require_permission
from app.gateway.deps import get_config, get_project_document_repo, get_project_repo, get_thread_store
from app.gateway.routers.uploads import DEFAULT_MAX_FILE_SIZE, UPLOAD_CHUNK_SIZE, _get_upload_limit, reserve_upload_write
from app.gateway.upload_ingestion import ThreadUploadIngestionService, UnsafeFilenameError, UnsafeUploadDestinationError
from deerflow.config.app_config import AppConfig
from deerflow.config.paths import Paths, get_paths
from deerflow.projects.documents import (
    ShelfContentMissingError,
    ShelfUploadTooLargeError,
    _content_intact_batch,
    add_staged_document,
    check_document_content,
    read_file_chunks,
    resolve_document_paths,
    stage_document_bytes,
    stage_document_copy_for_attach,
    validate_shelf_filename,
)
from deerflow.runtime import ConflictError
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.uploads.manager import normalize_filename
from deerflow.utils.file_io import await_drained, run_file_io
from deerflow.utils.text_detection import _is_active_content_mime_type, is_text_file_by_content
from deerflow.utils.thread_id import ThreadId

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects/{project_id}/documents", tags=["project-documents"])


class ProjectDocumentResponse(BaseModel):
    """One active shelf row. Internal columns (``user_id``, ``stored_relpath``,
    trash fields) never leave the server; trashed rows never reach it."""

    id: str
    name: str
    size_bytes: int
    sha256: str
    source_thread_id: str | None = None
    source_kind: str | None = None
    source_name: str | None = None
    created_at: str
    updated_at: str
    #: Read-time truth (never a persisted column): the immutable original is
    #: missing or size-mismatched — external interference, §8.3/§11. The
    #: derived companion is not the integrity anchor; the original is.
    content_missing: bool = False


class ProjectDocumentListResponse(BaseModel):
    documents: list[ProjectDocumentResponse]
    total: int
    limit: int
    offset: int


class ProjectDocumentUploadResponse(BaseModel):
    """``deduplicated`` distinguishes the 200 hit (existing row, first name

    wins, §10.9) from the 201 created row."""

    document: ProjectDocumentResponse
    deduplicated: bool


def _to_response(row: dict, *, content_missing: bool = False) -> ProjectDocumentResponse:
    return ProjectDocumentResponse(
        id=row["id"],
        name=row.get("name", ""),
        size_bytes=row.get("size_bytes", 0),
        sha256=row.get("sha256", ""),
        source_thread_id=row.get("source_thread_id"),
        source_kind=row.get("source_kind"),
        source_name=row.get("source_name"),
        created_at=row.get("created_at", ""),
        updated_at=row.get("updated_at", ""),
        content_missing=content_missing,
    )


def _not_found() -> HTTPException:
    # Fail closed: foreign projects/documents are indistinguishable from missing.
    return HTTPException(status_code=404, detail="Project document not found")


#: Non-text MIME families a browser renders inline WITHOUT executing script
#: on the application origin (the sandboxed preview iframe navigates to the
#: content endpoint). Active content (HTML/XML family) is never viewable.
_INLINE_VIEWABLE_MIME_PREFIXES = ("image/", "audio/", "video/")


def _is_inline_viewable_mime_type(media_type: str) -> bool:
    """Whether *media_type* may be served ``inline`` when ``download=false``.

    Passive text and browser-viewable binaries (PDF, image, audio, video)
    are inline-able; active content — HTML or any XML family type, including
    ``+xml`` subtypes such as SVG — never is (same rule as the artifacts
    router), regardless of the ``download`` flag.
    """
    if _is_active_content_mime_type(media_type):
        return False
    return media_type.startswith("text/") or media_type == "application/pdf" or media_type.startswith(_INLINE_VIEWABLE_MIME_PREFIXES)


async def _require_project(request: Request, project_id: str) -> dict:
    """Owned project row in any status (archived keeps read access, §8.4), else 404."""
    row = await get_project_repo(request).get(project_id)
    if row is None:
        raise _not_found()
    return row


async def _stream_upload(file: UploadFile) -> AsyncIterator[bytes]:
    while chunk := await file.read(UPLOAD_CHUNK_SIZE):
        yield chunk


@router.get("", response_model=ProjectDocumentListResponse)
@require_permission("projects", "read")
async def list_project_documents(
    project_id: str,
    request: Request,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> ProjectDocumentListResponse:
    await _require_project(request, project_id)
    repo = get_project_document_repo(request)
    rows = await repo.list_active(project_id, limit=limit, offset=offset)
    total = await repo.count_active(project_id)
    # Read-time integrity truth for the whole page in ONE offloaded pass:
    # files can only change via external interference, so the list surfaces
    # content_missing without a schema column (§8.3/§11).
    intact = await run_file_io(_content_intact_batch, get_paths(), user_id=get_effective_user_id(), rows=rows)
    return ProjectDocumentListResponse(
        documents=[_to_response(row, content_missing=not ok) for row, ok in zip(rows, intact, strict=True)],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=ProjectDocumentUploadResponse, status_code=201)
@require_permission("projects", "write")
async def upload_project_document(
    project_id: str,
    request: Request,
    response: Response,
    file: UploadFile = File(...),
    name: str | None = Form(default=None),
    config: AppConfig = Depends(get_config),
) -> ProjectDocumentUploadResponse:
    """Shelf exactly one file (§17.2): 201 created, or 200 on a content dedup hit.

    Active projects only — the shelf insert locks the project row with
    ``status='active'`` inside its transaction, so an archived/foreign/missing
    project is the same 404 (§8.4, §11). The display name defaults to the
    multipart filename; both go through the same validation (400 when empty,
    separator-bearing, or over 255 UTF-8 bytes). Size reuses
    ``uploads.max_file_size`` (413, mirroring the uploads router).
    """
    try:
        display_name = validate_shelf_filename(name) if name is not None else validate_shelf_filename(normalize_filename(file.filename or ""))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    user_id = get_effective_user_id()
    paths = get_paths()
    max_file_size = _get_upload_limit(config, "max_file_size", DEFAULT_MAX_FILE_SIZE, legacy_key="max_single_file_size")
    try:
        staged = await stage_document_bytes(paths, user_id=user_id, project_id=project_id, chunks=_stream_upload(file), max_bytes=max_file_size)
    except ShelfUploadTooLargeError:
        raise HTTPException(status_code=413, detail=f"File too large: {display_name}")
    except ValueError:
        # Unsafe project_id charset — fail closed, indistinguishable from missing.
        raise _not_found()
    if staged.size_bytes == 0:
        await run_file_io(staged.staging_path.unlink, True)
        raise HTTPException(status_code=400, detail="Empty file")

    result = await add_staged_document(
        get_project_document_repo(request),
        paths,
        user_id=user_id,
        project_id=project_id,
        name=display_name,
        staged=staged,
        source_kind="upload",
    )
    if result is None:
        raise _not_found()
    row, created = result
    if not created:
        # Dedup hit: same body, 200 instead of 201 — the first writer's name
        # and provenance win (§10.9).
        response.status_code = 200
    return ProjectDocumentUploadResponse(document=_to_response(row), deduplicated=not created)


class PromoteThreadFileRequest(BaseModel):
    """Save-to-shelf body (§7.4): locate one thread file, optional shelf rename."""

    thread_id: str
    kind: Literal["upload", "output"]
    name: str
    shelf_name: str | None = None


class AttachDocumentResponse(BaseModel):
    """The completed thread attachment — returned only after ingestion succeeds (§7.3 item 3)."""

    filename: str
    size_bytes: int
    virtual_path: str
    artifact_url: str


def _resolve_thread_source(paths: Paths, *, user_id: str, thread_id: str, kind: str, name: str) -> Path | None:
    """Resolve the source file inside the thread's own uploads/outputs dir.

    Confinement failure is indistinguishable from absence (§11): a separator-
    bearing or dot name, an escape of the thread directory (a symlink is
    followed and re-checked), a missing file, or an unsafe thread id all
    return ``None`` → 404. The boundary is the TRUSTED thread storage root —
    established unresolved from the server-owned base (resolving it would let
    a planted symlink turn an external directory into the trusted base and
    break user-bucket isolation): the resolved kind directory must live under
    that root, and the resolved candidate under the kind directory, so a
    symlinked uploads/outputs dir escaping thread storage is ``None`` while
    an in-root symlink keeps working (same behavior as virtual-path
    resolution). Runs in the file-IO worker (called via ``run_file_io``).
    """
    if not name or name in (".", "..") or "/" in name or "\\" in name:
        return None
    try:
        thread_root = paths.thread_dir(thread_id, user_id=user_id)
        kind_dir = (paths.sandbox_uploads_dir(thread_id, user_id=user_id) if kind == "upload" else paths.sandbox_outputs_dir(thread_id, user_id=user_id)).resolve()
        kind_dir.relative_to(thread_root)
        candidate = (kind_dir / name).resolve()
        candidate.relative_to(kind_dir)
    except (ValueError, OSError):
        return None
    return candidate if candidate.is_file() else None


@router.post("/from-thread", response_model=ProjectDocumentUploadResponse, status_code=201)
@require_permission("projects", "write")
@require_permission("threads", "read")
async def promote_thread_file_to_shelf(
    project_id: str,
    body: PromoteThreadFileRequest,
    request: Request,
    response: Response,
    config: AppConfig = Depends(get_config),
) -> ProjectDocumentUploadResponse:
    """Copy one thread file (upload or output) into the shelf (§7.4).

    The source is never moved — the shelf gets a project-owned snapshot with
    provenance (``source_thread_id``/``source_kind``/``source_name``), so
    deleting the thread cannot affect it. ``shelf_name`` defaults to the
    source name and follows upload-name validation. The shelf insert locks
    the project row with ``status='active'``, so an archived/foreign/missing
    project is the same 404 as a source that fails confinement (§8.4, §11).
    Response mirrors upload: 201 created, 200 on a content dedup hit (the
    existing row keeps its own name and provenance, §10.9).
    """
    if await get_thread_store(request).get(body.thread_id) is None:
        raise _not_found()
    repo = get_project_document_repo(request)
    try:
        display_name = validate_shelf_filename(body.shelf_name) if body.shelf_name is not None else validate_shelf_filename(normalize_filename(body.name))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    user_id = get_effective_user_id()
    paths = get_paths()
    source = await run_file_io(_resolve_thread_source, paths, user_id=user_id, thread_id=body.thread_id, kind=body.kind, name=body.name)
    if source is None:
        raise _not_found()

    max_file_size = _get_upload_limit(config, "max_file_size", DEFAULT_MAX_FILE_SIZE, legacy_key="max_single_file_size")
    try:
        staged = await stage_document_bytes(paths, user_id=user_id, project_id=project_id, chunks=read_file_chunks(source, chunk_size=UPLOAD_CHUNK_SIZE), max_bytes=max_file_size)
    except ShelfUploadTooLargeError:
        raise HTTPException(status_code=413, detail=f"File too large: {display_name}")
    except ValueError:
        # Unsafe project_id charset — fail closed, indistinguishable from missing.
        raise _not_found()
    if staged.size_bytes == 0:
        await run_file_io(staged.staging_path.unlink, True)
        raise HTTPException(status_code=400, detail="Empty file")

    result = await add_staged_document(
        repo,
        paths,
        user_id=user_id,
        project_id=project_id,
        name=display_name,
        staged=staged,
        source_thread_id=body.thread_id,
        source_kind=body.kind,
        source_name=body.name,
    )
    if result is None:
        raise _not_found()
    row, created = result
    if not created:
        # Dedup hit: same body, 200 instead of 201 — the first writer's name
        # and provenance win (§10.9).
        response.status_code = 200
    return ProjectDocumentUploadResponse(document=_to_response(row), deduplicated=not created)


@router.post("/{document_id}/attach-to-thread/{thread_id}", response_model=AttachDocumentResponse)
@require_permission("projects", "write")
@require_permission("threads", "write", owner_check=True, require_existing=True)
async def attach_project_document_to_thread(
    project_id: str,
    document_id: str,
    thread_id: ThreadId,
    request: Request,
    config: AppConfig = Depends(get_config),
) -> AttachDocumentResponse:
    """Materialize an independent copy of a shelf document into a thread (§7.3 item 3).

    The owned LIVE source document (an archived source project stays
    readable, §8.4 — its shelf is not mutated) is staged to a stable copy
    under its row lock, serialized against purge; the lock is then released
    and the shared thread-upload ingestion service takes over with ordinary
    upload lifecycle guarantees — size checks, optional conversion,
    sandbox-readable permissions, and non-mounted provider sync. Filename
    claiming is seeded from the thread's EXISTING uploads first, so the
    shelf copy never silently replaces a same-named thread file: it lands
    under a claimed unique name (``report_1.txt``), which the response
    reflects.
    The document transaction is never held across sandbox allocation or
    network sync. A target thread the caller cannot write is a 404 (the
    owner check above, ``require_existing``); the response is returned only
    after ingestion succeeds.
    """
    try:
        async with reserve_upload_write(thread_id, request):
            # The route's earlier owner check can become stale before admission.
            if not await get_thread_store(request).check_access(thread_id, get_effective_user_id(), require_existing=True):
                raise _not_found()
            return await await_drained(_attach_project_document_owned(project_id, document_id, thread_id, request, config))
    except ConflictError:
        raise HTTPException(status_code=409, detail="Thread has unfinished work. Retry the attachment when it is available.") from None


async def _attach_project_document_owned(project_id: str, document_id: str, thread_id: str, request: Request, config: AppConfig) -> AttachDocumentResponse:
    """Keep the target reservation until staged copy, ingestion and cleanup drain."""
    await _require_project(request, project_id)
    repo = get_project_document_repo(request)
    user_id = get_effective_user_id()
    paths = get_paths()
    try:
        staged = await stage_document_copy_for_attach(repo, paths, user_id=user_id, project_id=project_id, document_id=document_id)
    except ShelfContentMissingError:
        raise HTTPException(status_code=409, detail="content_missing")
    except ValueError:
        # Unsafe project_id charset — fail closed, indistinguishable from missing.
        raise _not_found()
    if staged is None:
        raise _not_found()
    row, staged_path = staged

    service = ThreadUploadIngestionService(request=request, thread_id=thread_id, user_id=user_id, app_config=config)
    try:
        try:
            await service.open()
            file_info = await service.ingest_chunks(read_file_chunks(staged_path, chunk_size=UPLOAD_CHUNK_SIZE), display_name=row["name"])
        except UnsafeFilenameError as exc:
            # Shelf names always normalize, so this cannot fire — fail closed.
            await service.cleanup_written()
            raise HTTPException(status_code=500, detail=f"Failed to upload {row['name']}: {exc}")
        except UnsafeUploadDestinationError as exc:
            await service.cleanup_written()
            raise HTTPException(status_code=500, detail=f"Failed to upload {row['name']}: {exc}")
        except HTTPException:
            await service.cleanup_written()
            raise
        except Exception as exc:
            logger.error(f"Failed to attach {row['name']} to thread {thread_id}: {exc}")
            await service.cleanup_written()
            raise HTTPException(status_code=500, detail=f"Failed to upload {row['name']}: {exc}")
        # Sync-phase failures (permissions/provider sync) follow ordinary
        # uploads: they propagate and the host files stay in place.
        await service.finalize()
    finally:
        await run_file_io(staged_path.unlink, True)
        await service.aclose()
    return AttachDocumentResponse(
        filename=file_info["filename"],
        size_bytes=file_info["size"],
        virtual_path=file_info["virtual_path"],
        artifact_url=file_info["artifact_url"],
    )


@router.get("/{document_id}/content")
@require_permission("projects", "read")
async def get_project_document_content(
    project_id: str,
    document_id: str,
    request: Request,
    download: bool = Query(default=False),
) -> FileResponse:
    """Inline text or attachment for one active shelf document (§6.5).

    ``download=false`` serves text inline (the converted-markdown companion
    when present, else the original when it samples as text) plus
    browser-viewable binaries — PDF, image, audio, video — for the sandboxed
    preview iframe, and streams other binaries as attachments.
    ``download=true`` always attaches the immutable ORIGINAL bytes under the
    original filename — the converted-markdown companion is preview-only, so
    a prior agent read never changes the download's format. Active content
    (HTML and the XML family, including ``+xml`` subtypes) is always forced to
    an attachment regardless of ``download`` so it never executes script on
    the application origin. A row whose original bytes are missing or
    size-mismatched answers with an explicit ``content_missing`` error (§11) —
    never an empty or substituted body.
    """
    await _require_project(request, project_id)
    row = await get_project_document_repo(request).get(document_id)
    if row is None or row.get("project_id") != project_id:
        raise _not_found()

    paths = get_paths()
    user_id = get_effective_user_id()
    # Validate the immutable ORIGINAL (existence AND recorded size, the one
    # shared §8.3 check) before selecting EITHER serving path: the derived
    # companion is only servable while its owning original validates (§6.2) —
    # a deleted or truncated original is ``content_missing``, never a healthy
    # preview.
    if not await check_document_content(paths, user_id=user_id, row=row):
        raise HTTPException(status_code=409, detail="content_missing")
    original, derived = await run_file_io(resolve_document_paths, paths, user_id=user_id, relpath=row["stored_relpath"], name=row["name"])

    serving_path = original
    media_type: str | None = None
    filename = row["name"]
    # The converted-markdown companion is a PREVIEW aid only: an explicit
    # download always serves the immutable original bytes under the original
    # filename — never a format that changed because an agent once read it.
    if not download and await run_file_io(derived.is_file):
        serving_path = derived
        media_type = "text/markdown"
        filename = f"{row['name']}.md"
    else:
        guessed, _ = await run_file_io(mimetypes.guess_type, str(original))
        media_type = guessed
    if media_type is None and not download and await run_file_io(is_text_file_by_content, serving_path):
        media_type = "text/plain"

    # Inline only what a browser can display WITHOUT running script on the
    # application origin: passive text, the converted-markdown companion, and
    # browser-viewable binaries (PDF, image, audio, video — the sandboxed
    # preview iframe navigates here). Active content (HTML or any XML family
    # type, including ``+xml`` subtypes such as SVG) is ALWAYS an attachment
    # regardless of ``download``, exactly like the artifacts router, and
    # ``download=true`` attaches everything.
    inline = not download and media_type is not None and _is_inline_viewable_mime_type(media_type)
    return FileResponse(
        serving_path,
        media_type=media_type or "application/octet-stream",
        filename=filename,
        # nosniff: a declared PDF/image/etc. must never be reinterpreted as
        # HTML — the transport-level guarantee behind unsandboxed PDF preview.
        headers={"X-Content-Type-Options": "nosniff"},
        content_disposition_type="inline" if inline else "attachment",
    )


@router.delete("/{document_id}", status_code=204)
@require_permission("projects", "delete")
async def delete_project_document(project_id: str, document_id: str, request: Request) -> None:
    """Move one document to trash (204). Restore/purge are the Slice-D trash tier.

    Archived shelves reject the write inside the repository's locked
    transaction, so they surface as the same fail-closed 404 (§8.4).
    """
    await _require_project(request, project_id)
    if not await get_project_document_repo(request).trash(document_id, project_id=project_id):
        raise _not_found()
````

## backend/packages/harness/deerflow/projects/documents.py

````python
"""Project document shelf service: staging, atomic insert, conversion.

Implements the Phase-2 shelf-insert atomicity (spec §6.3): bytes are staged
under ``.staging/{uuid}``, hashed, then — inside the repository's one
transaction (active-project row lock → dedup select → insert) — atomically
renamed into the document's exclusive namespace **before** the row exists
(file-before-row, §10.3). A dedup hit removes staging and returns the existing
row (the first writer's name wins, §10.9); a failed insert cleans up only its
own namespace, best-effort. Every filesystem operation runs off the event
loop via :func:`deerflow.utils.file_io.run_file_io`.

Files are immutable and hash-qualified: ``stored_relpath`` (relative to
``users/{user_id}/projects/``) embeds the content hash and the row's own
document ID, so rows never share bytes and a re-upload after trash lands in a
fresh namespace (§6.2). Conversion is lazy: a convertible original is turned
into ``derived/converted.md`` on first read, written through a temporary file
and an atomic rename, and only when ``uploads.auto_convert_documents`` is on
(§6.4, §7.3).
"""

from __future__ import annotations

import asyncio
import codecs
import hashlib
import logging
import os
import shutil
import uuid
from collections import OrderedDict
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from deerflow.config.paths import Paths
from deerflow.utils.file_conversion import CONVERTIBLE_EXTENSIONS, convert_file_to_markdown
from deerflow.utils.file_io import run_file_io
from deerflow.utils.text_detection import is_text_file_by_content

if TYPE_CHECKING:
    from deerflow.persistence.projects import ProjectDocumentRepository

logger = logging.getLogger(__name__)

_MAX_FILENAME_BYTES = 255


def _filesystem_path(path: Path) -> Path:
    """Use Windows' extended-length form after safe namespace resolution."""
    if os.name != "nt" or str(path).startswith("\\\\?\\") or len(str(path)) < 248:
        return path
    raw = str(path)
    return Path(f"\\\\?\\UNC\\{raw[2:]}") if raw.startswith("\\\\") else Path(f"\\\\?\\{raw}")


class ShelfUploadTooLargeError(Exception):
    """Raised when staged bytes exceed ``uploads.max_file_size`` (mapped to 413)."""


def validate_shelf_filename(name: str) -> str:
    """Normalize and validate a shelf display filename; ``ValueError`` ⇒ 400.

    The display filename occupies its own path component (no hash prefix or
    suffix), so it must be a bare, non-empty filename within the 255 UTF-8
    byte filesystem limit — path separators are rejected outright rather than
    stripped (§6.5).
    """
    candidate = name.strip() if name else ""
    if not candidate:
        raise ValueError("Filename is empty")
    if "/" in candidate or "\\" in candidate:
        raise ValueError(f"Filename contains a path separator: {name!r}")
    if candidate in {".", ".."}:
        raise ValueError(f"Filename is unsafe: {name!r}")
    if len(candidate.encode("utf-8")) > _MAX_FILENAME_BYTES:
        raise ValueError(f"Filename exceeds {_MAX_FILENAME_BYTES} UTF-8 bytes")
    return candidate


def shelf_relpath(project_id: str, sha256: str, document_id: str) -> str:
    """Content-addressed namespace root for one row, relative to ``users/{user_id}/projects/``."""
    return f"{project_id}/documents/{sha256[:2]}/{sha256}/{document_id}"


def original_file_path(paths: Paths, *, user_id: str, row: dict) -> Path:
    """Absolute host path of a row's immutable original bytes."""
    return resolve_document_paths(paths, user_id=user_id, relpath=row["stored_relpath"], name=row["name"])[0]


def converted_markdown_path(paths: Paths, *, user_id: str, row: dict) -> Path:
    """Absolute host path of a row's optional ``derived/converted.md`` companion."""
    return resolve_document_paths(paths, user_id=user_id, relpath=row["stored_relpath"], name=row["name"])[1]


def resolve_document_paths(paths: Paths, *, user_id: str, relpath: str, name: str) -> tuple[Path, Path]:
    """Resolve a row's ``(original, derived)`` host paths — worker-thread only on async paths.

    ``Paths.project_document_path`` resolves symlinks against the real
    filesystem, so async callers MUST dispatch this through ``run_file_io``
    (filesystem-offload convention); the helper itself stays sync because it
    is also used from worker contexts already off the loop.
    """
    namespace = paths.project_document_path(user_id, relpath)
    return _filesystem_path(namespace / "original" / name), _filesystem_path(namespace / "derived" / "converted.md")


def _content_intact(paths: Paths, *, user_id: str, row: dict) -> bool:
    """Worker-thread: resolve the original and verify it exists and matches the row's recorded size."""
    original = original_file_path(paths, user_id=user_id, row=row)
    try:
        return original.stat().st_size == int(row.get("size_bytes") or -1)
    except OSError:
        return False


async def check_document_content(paths: Paths, *, user_id: str, row: dict) -> bool:
    """True when the row's immutable original exists and matches ``size_bytes``.

    The one content check shared by the text serving path, restore (under
    the document lock), the content endpoint, and the retention sweep's row
    reconciliation (§8.3/§11): missing or size-mismatched bytes mean external
    interference — reported as ``content_missing``, never served, repaired,
    or treated as an empty document.
    """
    return await run_file_io(_content_intact, paths, user_id=user_id, row=row)


def _content_intact_batch(paths: Paths, *, user_id: str, rows: list[dict]) -> list[bool]:
    """Worker-thread: existence+size check for a whole page of rows in one offload pass."""
    return [_content_intact(paths, user_id=user_id, row=row) for row in rows]


@dataclass(slots=True)
class StagedDocument:
    """Bytes staged under ``.staging/`` with their content address."""

    staging_path: Path
    sha256: str
    size_bytes: int


def _open_staging(staging_dir: Path, staging_path: Path):
    """Worker-thread: create the staging directory and open the staging file."""
    staging_dir.mkdir(parents=True, exist_ok=True)
    return open(staging_path, "wb")


def _close_and_unlink(handle: Any, staging_path: Path) -> None:
    try:
        handle.close()
    finally:
        staging_path.unlink(missing_ok=True)


async def stage_document_bytes(paths: Paths, *, user_id: str, project_id: str, chunks: AsyncIterator[bytes] | list[bytes], max_bytes: int) -> StagedDocument:
    """Stage upload/promote bytes off-loop, enforcing the single-file size cap.

    Chunks are streamed to ``.staging/{uuid}`` (writes offloaded one by one,
    the uploads router's discipline) while the content hash accumulates.
    ``max_bytes`` is the thread-upload limit (``uploads.max_file_size``) —
    the shelf deliberately reuses it instead of growing a second knob with
    the same meaning (§6.4). Overflow raises :class:`ShelfUploadTooLargeError`
    (the route maps it to 413, mirroring the uploads router) and leaves no
    staging file behind.
    """
    staging_dir = paths.project_documents_dir(user_id, project_id) / ".staging"
    staging_path = staging_dir / uuid.uuid4().hex
    handle = await run_file_io(_open_staging, staging_dir, staging_path)
    digest = hashlib.sha256()
    size = 0

    async def _aiter() -> AsyncIterator[bytes]:
        if isinstance(chunks, list):
            for chunk in chunks:
                yield chunk
        else:
            async for chunk in chunks:
                yield chunk

    try:
        async for chunk in _aiter():
            size += len(chunk)
            if size > max_bytes:
                raise ShelfUploadTooLargeError(f"File exceeds the {max_bytes}-byte limit")
            digest.update(chunk)
            await run_file_io(handle.write, chunk)
        await run_file_io(handle.close)
    except Exception:
        await run_file_io(_close_and_unlink, handle, staging_path)
        raise
    return StagedDocument(staging_path=staging_path, sha256=digest.hexdigest(), size_bytes=size)


def _place_staging(staging_path: Path, final_path: Path) -> None:
    """Atomically move staged bytes into the document's exclusive namespace."""
    final_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(staging_path, final_path)
    except Exception:
        staging_path.unlink(missing_ok=True)
        raise


def _remove_staging(staging_path: Path) -> None:
    staging_path.unlink(missing_ok=True)


def _remove_namespace(paths: Paths, *, user_id: str, relpath: str) -> None:
    """Best-effort removal of one document's exclusive namespace (never another row's)."""
    shutil.rmtree(paths.project_document_path(user_id, relpath), ignore_errors=True)


async def add_staged_document(
    repo: ProjectDocumentRepository,
    paths: Paths,
    *,
    user_id: str,
    project_id: str,
    name: str,
    staged: StagedDocument,
    source_thread_id: str | None = None,
    source_kind: str | None = None,
    source_name: str | None = None,
) -> tuple[dict, bool] | None:
    """Publish staged bytes as a shelf row, or fold into the dedup hit.

    Returns ``(row, created)`` — ``created`` is ``False`` for a dedup hit, in
    which case the returned row is the pre-existing one (its name and
    provenance win, §10.9) and the staged bytes are discarded. ``None`` means
    the project is missing, foreign, or archived (the route maps it to 404).
    A failure removes this document's namespace only when the row PROVABLY
    does not exist: a post-commit failure (e.g. the insert's trailing
    refresh) leaves the live row serving its placed bytes and is reported as
    success, and an indeterminate liveness check leaves the namespace for
    the reference-aware sweep (§8.3).
    """
    document_id = uuid.uuid4().hex
    relpath = shelf_relpath(project_id, staged.sha256, document_id)
    # Symlink-resolving lookup — offloaded like every filesystem touch here.
    final_path = (await run_file_io(resolve_document_paths, paths, user_id=user_id, relpath=relpath, name=name))[0]

    async def _place() -> None:
        await run_file_io(_place_staging, staged.staging_path, final_path)

    try:
        row = await repo.insert_active(
            project_id,
            document_id=document_id,
            name=name,
            relpath=relpath,
            sha256=staged.sha256,
            size_bytes=staged.size_bytes,
            source_thread_id=source_thread_id,
            source_kind=source_kind,
            source_name=source_name,
            place_file=_place,
            user_id=user_id,
        )
    except Exception:
        # ``insert_active`` owns its commit: a failure may surface AFTER the
        # row committed (e.g. its trailing refresh), so the placed namespace
        # is removed only when the row PROVABLY does not exist. When the row
        # is live the insert effectively succeeded — the shelf already serves
        # these bytes — so return it instead of raising; when liveness cannot
        # be determined, leave the namespace for the reference-aware
        # retention sweep (§8.3), which only collects unreferenced files and
        # protects any row's namespace. The probe includes TRASHED rows: a
        # row raced into trash (or a trashing project deletion) before the
        # re-check still owns the placed bytes — trash is recoverable, so
        # deleting the namespace would destroy a recoverable document.
        await run_file_io(_remove_staging, staged.staging_path)
        committed: dict | None
        try:
            committed = await repo.get(document_id, include_trashed=True, user_id=user_id)
        except Exception:
            committed = None
            row_provably_absent = False
            logger.warning(
                "Shelf insert of %s failed and the liveness re-check failed too; leaving the namespace for the retention sweep",
                document_id,
                exc_info=True,
            )
        else:
            row_provably_absent = committed is None
        if committed is not None:
            if committed.get("trashed_at") is None:
                logger.warning("Shelf insert of %s raised after commit; the row is live — keeping its namespace and reporting success", document_id)
                return committed, True
            # Committed but raced into trash before the re-check: keep the
            # bytes recoverable in trash and surface the failure rather than
            # presenting a trashed row as created.
            logger.warning("Shelf insert of %s raised after commit and the row was trashed meanwhile; keeping its namespace in trash", document_id)
        elif row_provably_absent:
            # Confirmed rollback: the bytes are unreferenced — clean up only
            # this document's own namespace (§6.3).
            await run_file_io(_remove_namespace, paths, user_id=user_id, relpath=relpath)
        raise
    if row is None:
        # Missing/foreign/archived project: nothing was placed or inserted.
        await run_file_io(_remove_staging, staged.staging_path)
        return None
    if row["id"] != document_id:
        # Dedup hit: the existing row wins; discard the staged duplicate.
        await run_file_io(_remove_staging, staged.staging_path)
        return row, False
    return row, True


def _convert_in_thread(original: Path, output_path: Path) -> Path | None:
    """Run the async conversion engine on a private loop inside the worker.

    ``convert_file_to_markdown`` offloads its own heavy work (>1 MiB) but
    stats and writes on its caller's loop; running the whole coroutine here
    keeps every byte of the conversion path off the serving event loop.
    """
    return asyncio.run(convert_file_to_markdown(original, output_path=output_path))


def _convert_and_publish(original: Path, derived: Path) -> bool:
    """Worker-thread body: convert to a temp file, then atomically publish.

    The temp file lives beside the final path (same filesystem) so the
    rename is atomic: readers only ever see a complete ``converted.md`` or
    none at all. A conversion failure publishes nothing and removes the temp.
    """
    derived.parent.mkdir(parents=True, exist_ok=True)
    temp_path = derived.parent / f".{derived.name}.{uuid.uuid4().hex}.tmp"
    try:
        produced = _convert_in_thread(original, temp_path)
        if produced is None:
            return False
        os.replace(produced, derived)
        return True
    except Exception:
        logger.warning("Failed to convert shelf document %s", original, exc_info=True)
        temp_path.unlink(missing_ok=True)
        return False
    finally:
        temp_path.unlink(missing_ok=True)


async def ensure_converted_markdown(repo: ProjectDocumentRepository, paths: Paths, *, user_id: str, row: dict, auto_convert: bool) -> tuple[Path | None, str | None]:
    """Return ``(converted_path, None)`` or ``(None, reason)``, converting on first read.

    Conversion runs — and ``derived/converted.md`` is published — while the
    repository holds the document row lock, with ownership, shelf membership
    and active state revalidated AFTER locking (§6.3): a trash/purge that
    committed first makes this decline as ``content_missing`` without
    converting or publishing anything, and one arriving during conversion
    blocks on the row lock and then proceeds. The temp-file + atomic
    ``os.replace`` publish stays inside the lock, so no partial converted
    text is ever exposed. The published companion is valid for the lifetime
    of the row's immutable original and never needs invalidation (§6.2,
    §10.9). ``reason`` is one of ``"conversion_disabled"`` (auto-convert
    off, §7.3), ``"content_missing"`` (row no longer live), or ``"binary"``
    (not convertible, or the conversion itself failed).
    """
    if not auto_convert:
        return None, "conversion_disabled"
    original, derived = await run_file_io(resolve_document_paths, paths, user_id=user_id, relpath=row["stored_relpath"], name=row["name"])
    if original.suffix.lower() not in CONVERTIBLE_EXTENSIONS:
        return None, "binary"
    if await run_file_io(derived.is_file):
        return derived, None

    async def _convert(_locked_row: dict) -> bool:
        # Re-check under the lock: a conversion that blocked on this row's
        # lock may already have been published by the lock's previous holder.
        if await run_file_io(derived.is_file):
            return True
        return await run_file_io(_convert_and_publish, original, derived)

    locked = await repo.convert_under_live_lock(row["id"], project_id=row["project_id"], convert=_convert, user_id=user_id)
    if locked is None:
        # Purged/trashed (or foreign) between the caller's read and the
        # locked revalidation: decline without publishing anything (§6.3).
        return None, "content_missing"
    _locked_row, published = locked
    return (derived, None) if published else (None, "binary")


async def read_text_serving_path(repo: ProjectDocumentRepository, paths: Paths, *, user_id: str, row: dict, auto_convert: bool) -> tuple[Path | None, str | None]:
    """Resolve which file serves a row's text reads, or why none can.

    Returns ``(path, None)`` for a servable text source — the cached
    ``derived/converted.md``, the original when it samples as text, or a
    freshly converted companion — and ``(None, reason)`` otherwise, where
    ``reason`` is one of ``"content_missing"``, ``"conversion_disabled"`` or
    ``"binary"`` so the caller can produce the §11 error without re-deriving
    the classification. The immutable ORIGINAL is validated (existence AND
    recorded size, the shared §8.3 check) before either serving source is
    selected: a truncated or zero-byte original is ``content_missing``, never
    served as complete, and the derived companion is only servable while its
    owning original validates (§6.2). A convertible extension
    (``CONVERTIBLE_EXTENSIONS``) takes the conversion path — or the
    ``conversion_disabled`` decline — BEFORE the text heuristic: a
    null-free head (e.g. an ASCII85 PDF) must never be raw-served as text.
    Genuine text extensions keep the sampled-head heuristic (no
    ``mime``/``is_text`` columns exist by design, §6.1).
    """
    if not await check_document_content(paths, user_id=user_id, row=row):
        return None, "content_missing"
    original, derived = await run_file_io(resolve_document_paths, paths, user_id=user_id, relpath=row["stored_relpath"], name=row["name"])
    if await run_file_io(derived.is_file):
        return derived, None
    if original.suffix.lower() in CONVERTIBLE_EXTENSIONS:
        return await ensure_converted_markdown(repo, paths, user_id=user_id, row=row, auto_convert=auto_convert)
    if await run_file_io(is_text_file_by_content, original):
        return original, None
    return None, "binary"


#: Bounded decode window: reads stop once the requested character page is full.
_TEXT_READ_CHUNK = 65536

#: Bounded process-local LRU of decoded character counts, keyed by content
#: identity ``(document_id, sha256)``. Documents are immutable within a row's
#: lifetime (§6.2/§10.9) and ids are never reused, so a purge simply orphans
#: an entry until LRU eviction — no invalidation hook needed.
_CHAR_COUNT_CACHE: OrderedDict[tuple[str, str], int] = OrderedDict()
_CHAR_COUNT_CACHE_MAX = 256


def _read_text_window(path: Path, *, offset: int, limit: int) -> str:
    """Worker-thread: decode only enough of *path* to fill ``[offset, offset+limit)``.

    Incremental UTF-8 decode (replacement-tolerant, split-sequence safe) over
    bounded chunks: the full decoded string is never materialized and reading
    stops as soon as the window is filled, so an early page of a multi-MiB
    document never reads the whole file.
    """
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    parts: list[str] = []
    position = 0  # decoded characters seen so far
    end = offset + limit
    with open(path, "rb") as handle:
        while position < end:
            chunk = handle.read(_TEXT_READ_CHUNK)
            final = not chunk
            text = decoder.decode(chunk, final)
            if not text:
                if final:
                    break
                continue
            if position + len(text) > offset:
                parts.append(text[max(offset - position, 0) :])
            position += len(text)
            if final:
                break
    return "".join(parts)[:limit]


def _count_text_chars(path: Path) -> int:
    """Worker-thread: full scan-decode COUNT without materializing the string."""
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    total = 0
    with open(path, "rb") as handle:
        while chunk := handle.read(_TEXT_READ_CHUNK):
            total += len(decoder.decode(chunk))
    return total + len(decoder.decode(b"", True))


def _cached_char_count(document_id: str, sha256: str, path: Path) -> int:
    """Worker-thread: character count of an immutable document, cached by content identity."""
    key = (document_id, sha256)
    cached = _CHAR_COUNT_CACHE.get(key)
    if cached is not None:
        _CHAR_COUNT_CACHE.move_to_end(key)
        return cached
    total = _count_text_chars(path)
    _CHAR_COUNT_CACHE[key] = total
    while len(_CHAR_COUNT_CACHE) > _CHAR_COUNT_CACHE_MAX:
        _CHAR_COUNT_CACHE.popitem(last=False)
    return total


async def read_document_text_window(path: Path, *, offset: int, limit: int) -> str:
    """Decode the ``[offset, offset+limit)`` character window of a serving file, off-loop."""
    return await run_file_io(_read_text_window, path, offset=offset, limit=limit)


async def document_char_count(*, document_id: str, sha256: str, path: Path) -> int:
    """Total decoded characters of a serving file, off-loop and content-identity cached."""
    return await run_file_io(_cached_char_count, document_id, sha256, path)


def auto_convert_documents_enabled(app_config: Any) -> bool:
    """Return whether host-side document conversion is enabled (secure default off).

    Mirrors the uploads router's reader: a malformed value declines rather
    than crashing, and stringly-typed YAML booleans are honored.
    """
    try:
        uploads_cfg = getattr(app_config, "uploads", None)
        raw = uploads_cfg.get("auto_convert_documents", False) if isinstance(uploads_cfg, dict) else getattr(uploads_cfg, "auto_convert_documents", False)
        if isinstance(raw, str):
            return raw.strip().lower() in {"1", "true", "yes", "on"}
        return bool(raw)
    except Exception:
        return False


class ShelfContentMissingError(Exception):
    """A live row's original bytes are absent or size-mismatched (§11 ``content_missing``)."""


async def read_file_chunks(path: Path, *, chunk_size: int = 65536) -> AsyncIterator[bytes]:
    """Yield one file's bytes with every read off the event loop.

    Shared by the from-thread promote path (thread file → shelf staging) and
    the attach path (staged shelf copy → thread-upload ingestion).
    """

    def _open() -> Any:
        return open(path, "rb")

    handle = await run_file_io(_open)
    try:
        while chunk := await run_file_io(handle.read, chunk_size):
            yield chunk
    finally:
        await run_file_io(handle.close)


def _copy_original_under_lock(paths: Paths, staging_path: Path, *, user_id: str, row: dict) -> None:
    """Worker-thread: copy a live document's original to a stable staging file.

    Runs inside the document row lock (``stage_live_copy``): the bytes are
    immutable, so an absent file or a size disagreement means external
    interference — reported as ``content_missing``, never copied (§8.3).
    Resolving the original's path happens here too: ``project_document_path``
    resolves symlinks against the real filesystem, so it stays off the
    caller's event loop.
    """
    source = original_file_path(paths, user_id=user_id, row=row)
    expected_size = row.get("size_bytes")
    if not source.is_file():
        raise ShelfContentMissingError("original bytes are missing")
    if expected_size is not None and source.stat().st_size != expected_size:
        raise ShelfContentMissingError("original size disagrees with the row")
    staging_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, staging_path)


async def stage_document_copy_for_attach(
    repo: ProjectDocumentRepository,
    paths: Paths,
    *,
    user_id: str,
    project_id: str,
    document_id: str,
) -> tuple[dict, Path] | None:
    """Stage a stable copy of a live document's original under its row lock.

    §7.3 item 3: attach is serialized against purge/trash — the copy runs
    while the repository holds the document row lock, then the lock is
    released BEFORE the caller performs sandbox allocation/network sync.
    The copy lands in the project shelf's ``.staging/`` (a crash leftover is
    collected by the retention sweep's 24-hour orphan guard, §8.3) and is
    the caller's responsibility to unlink. ``None`` means the document is
    missing, foreign, trashed, or not on this project's shelf (the route
    maps it to 404); :class:`ShelfContentMissingError` maps to 409.
    """
    staging_path = paths.project_documents_dir(user_id, project_id) / ".staging" / f"attach-{uuid.uuid4().hex}"

    async def _copy(row: dict) -> Path:
        await run_file_io(_copy_original_under_lock, paths, staging_path, user_id=user_id, row=row)
        return staging_path

    result = await repo.stage_live_copy(document_id, project_id=project_id, stage=_copy, user_id=user_id)
    if result is None:
        return None
    row, staged_path = result
    return row, staged_path
````

## backend/app/gateway/authz.py

````python
"""Authorization decorators and context for DeerFlow.

Inspired by LangGraph Auth system: https://github.com/langchain-ai/langgraph/blob/main/libs/sdk-py/langgraph_sdk/auth/__init__.py

**Usage:**

1. Use ``@require_auth`` on routes that need authentication
2. Use ``@require_permission("resource", "action", filter_key=...)`` for permission checks
3. The decorator chain processes from bottom to top

**Example:**

    @router.get("/{thread_id}")
    @require_auth
    @require_permission("threads", "read", owner_check=True)
    async def get_thread(thread_id: str, request: Request):
        # User is authenticated and has threads:read permission
        ...

**Permission Model:**

- threads:read   - View thread
- threads:write  - Create/update thread
- threads:delete - Delete thread
- runs:create   - Run agent
- runs:read     - View run
- runs:cancel   - Cancel run
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, ParamSpec, TypeVar

from fastapi import HTTPException, Request

from deerflow.authz.principal import build_principal_from_context
from deerflow.authz.provider import AuthorizationProvider, AuthzDecision, AuthzRequest, Principal
from deerflow.authz.runtime import resolve_authorization_provider
from deerflow.config.authorization_config import AuthorizationConfig

if TYPE_CHECKING:
    from app.gateway.auth.models import User
    from deerflow.config.app_config import AppConfig

P = ParamSpec("P")
T = TypeVar("T")
logger = logging.getLogger(__name__)


# Permission constants
class Permissions:
    """Permission constants for resource:action format."""

    # Threads
    THREADS_READ = "threads:read"
    THREADS_WRITE = "threads:write"
    THREADS_DELETE = "threads:delete"

    # Runs
    RUNS_CREATE = "runs:create"
    RUNS_READ = "runs:read"
    RUNS_CANCEL = "runs:cancel"
    # Projects
    PROJECTS_READ = "projects:read"
    PROJECTS_WRITE = "projects:write"
    PROJECTS_DELETE = "projects:delete"
    # Clients
    CLIENTS_READ = "clients:read"
    CLIENTS_WRITE = "clients:write"
    CLIENTS_DELETE = "clients:delete"
    # Momo Board
    BOARD_READ = "board:read"
    BOARD_WRITE = "board:write"
    # Momentum-internal: team channels and AI Academy (staff only)
    TEAM_READ = "team:read"
    TEAM_WRITE = "team:write"
    ACADEMY_READ = "academy:read"
    ACADEMY_WRITE = "academy:write"
    # Approvals inbox: review/approve outbound actions agents proposed
    APPROVALS_READ = "approvals:read"
    APPROVALS_WRITE = "approvals:write"
    # Fleet hosts: claim, renew, finalize and release fleet-executed batch items
    FLEET_WORK = "fleet:work"


class AuthContext:
    """Authentication context for the current request.

    Stored in request.state.auth after require_auth decoration.

    Attributes:
        user: The authenticated user, or None if anonymous
        permissions: List of permission strings (e.g., "threads:read")
        organization_id: Active server-resolved organization for session/PAT callers
        actor_user_id: Authenticated human identity, retained for audit/credentials
        storage_user_id: Server-selected content storage principal
    """

    __slots__ = ("user", "permissions", "organization_id", "actor_user_id", "storage_user_id", "organization_role")

    def __init__(
        self,
        user: User | None = None,
        permissions: list[str] | None = None,
        organization_id: str | None = None,
        *,
        actor_user_id: str | None = None,
        storage_user_id: str | None = None,
        organization_role: str | None = None,
    ):
        self.user = user
        self.permissions = permissions or []
        self.organization_id = organization_id
        self.actor_user_id = actor_user_id
        self.storage_user_id = storage_user_id
        self.organization_role = organization_role

    @property
    def is_authenticated(self) -> bool:
        """Check if user is authenticated."""
        return self.user is not None

    def has_permission(self, resource: str, action: str) -> bool:
        """Check if context has permission for resource:action.

        Args:
            resource: Resource name (e.g., "threads")
            action: Action name (e.g., "read")

        Returns:
            True if user has permission
        """
        permission = f"{resource}:{action}"
        return permission in self.permissions

    def require_user(self) -> User:
        """Get user or raise 401.

        Raises:
            HTTPException 401 if not authenticated
        """
        if not self.user:
            raise HTTPException(status_code=401, detail="Authentication required")
        return self.user


def get_auth_context(request: Request) -> AuthContext | None:
    """Get AuthContext from request state."""
    return getattr(request.state, "auth", None)


def require_cancel_permission_if(request: Request, can_cancel: bool) -> None:
    """Require ``runs:cancel`` when a request carries cancel capability.

    Cancel capability reaches the run lifecycle through more than the dedicated
    cancel route: ``?action=interrupt|rollback`` on the join-stream entry and
    ``multitask_strategy=interrupt|rollback`` on run creation both terminate an
    already-active run. A credential whose scopes omit ``runs:cancel`` (e.g. a
    create- or read-only PAT) must not reach any of those paths, and
    decorators cannot express query- or body-parameter-conditional
    permissions, so callers apply this check where the capability is known.

    ``request.state.auth`` may be absent in middleware-less compositions
    (unit-test stubs, auth-disabled startup); the shipped Gateway always
    stamps it via ``AuthMiddleware`` before handlers run.
    """
    if not can_cancel:
        return
    auth = getattr(request.state, "auth", None)
    if auth is not None and not auth.has_permission("runs", "cancel"):
        raise HTTPException(status_code=403, detail="Permission denied: runs:cancel")


_ALL_PERMISSIONS: list[str] = [
    Permissions.THREADS_READ,
    Permissions.THREADS_WRITE,
    Permissions.THREADS_DELETE,
    Permissions.RUNS_CREATE,
    Permissions.RUNS_READ,
    Permissions.RUNS_CANCEL,
    Permissions.PROJECTS_READ,
    Permissions.PROJECTS_WRITE,
    Permissions.PROJECTS_DELETE,
    Permissions.CLIENTS_READ,
    Permissions.CLIENTS_WRITE,
    Permissions.CLIENTS_DELETE,
    Permissions.BOARD_READ,
    Permissions.BOARD_WRITE,
    Permissions.TEAM_READ,
    Permissions.TEAM_WRITE,
    Permissions.ACADEMY_READ,
    Permissions.ACADEMY_WRITE,
    Permissions.APPROVALS_READ,
    Permissions.APPROVALS_WRITE,
    Permissions.FLEET_WORK,
]


def _make_test_request_stub() -> Any:
    """Create a minimal request-like object for direct unit calls.

    Used when decorated route handlers are invoked without FastAPI's
    request injection. Includes fields accessed by auth helpers.
    """
    return SimpleNamespace(state=SimpleNamespace(), cookies={}, _deerflow_test_bypass_auth=True)


def _get_route_authorization_config() -> AuthorizationConfig:
    """Return the hot-reloaded authorization config for this request.

    Falls back to a disabled config when AppConfig is not available (e.g. test
    environments without a config.yaml), preserving legacy all-permissions behavior.
    """
    from deerflow.config.app_config import get_app_config

    try:
        return get_app_config().authorization
    except (FileNotFoundError, RuntimeError):
        return AuthorizationConfig()


# --- Provider cache (W1/F1) ---
# Keyed by config object identity (id) so the expensive model_dump() signature
# is only recomputed when get_app_config() returns a new object (hot-reload).
_route_provider_cache: dict[str, AuthorizationProvider] = {}
_route_provider_config_id: int | None = None
_route_provider_config_sig: str | None = None


def _get_cached_route_provider(config: AuthorizationConfig) -> AuthorizationProvider | None:
    """Resolve (or reuse) the authorization provider for route permissions.

    The provider is cached per config object identity. When ``get_app_config()``
    returns a new object (hot-reload), the signature is recomputed and compared;
    only an actual content change triggers re-resolution. This avoids calling
    ``model_dump()`` on every request — the fast path is a single ``id()`` check.
    """
    global _route_provider_config_id, _route_provider_config_sig, _route_provider_cache

    config_id = id(config)

    # Fast path: same config object as last time → return cached provider.
    if config_id == _route_provider_config_id and _route_provider_cache:
        return _route_provider_cache.get("provider")

    # Config object changed (hot-reload): compute signature to check if
    # content actually changed or just the wrapper object identity.
    sig = repr(sorted(config.model_dump().items()))
    if sig == _route_provider_config_sig and _route_provider_cache:
        # Same content, different object — update id, reuse provider.
        _route_provider_config_id = config_id
        return _route_provider_cache.get("provider")

    # Content changed (or first call): re-resolve into a local first,
    # then publish id + sig + provider together to avoid a race window.
    _route_provider_cache.clear()

    provider = resolve_authorization_provider(config)
    if provider is not None:
        _route_provider_cache["provider"] = provider
    _route_provider_config_id = config_id
    _route_provider_config_sig = sig
    return provider


async def resolve_route_permissions(user: User, *, is_internal: bool) -> list[str]:
    """Return the route permissions granted to an authenticated user.

    Disabled authorization preserves the legacy all-permissions behavior.
    When enabled, every registered ``resource:action`` permission is evaluated
    independently so a provider failure affects only the route being checked.
    Provider instances are cached per config signature (hot-reload safe).
    """
    config = _get_route_authorization_config()
    if config.enabled is not True:
        return list(_ALL_PERMISSIONS)

    try:
        provider = _get_cached_route_provider(config)
        if provider is None:
            raise ValueError("authorization is enabled but provider resolution returned None")
    except Exception:
        logger.warning("Failed to resolve authorization provider for Gateway routes", exc_info=True)
        return [] if config.fail_closed else list(_ALL_PERMISSIONS)

    # Align with Phase 1B's tool path: internal callers (IM channel workers,
    # scheduler) have system_role="internal", which is not a real RBAC role.
    # Omit it so default_role applies, mirroring inject_authenticated_user_context
    # which pops user_role for internal callers without a resolved owner.
    from app.gateway.internal_auth import INTERNAL_SYSTEM_ROLE

    user_role = getattr(user, "system_role", None)
    if user_role == INTERNAL_SYSTEM_ROLE:
        user_role = None

    principal = build_principal_from_context(
        {
            "user_id": str(user.id),
            "user_role": user_role,
            "oauth_provider": getattr(user, "oauth_provider", None),
            "oauth_id": getattr(user, "oauth_id", None),
            "is_internal": is_internal,
        },
        default_role=config.default_role,
    )

    # Evaluate all permissions in parallel (W2).
    async def _evaluate(permission: str) -> str | None:
        _, action = permission.split(":", maxsplit=1)
        request = AuthzRequest(
            principal=principal,
            resource="route",
            action=action,
            target=permission,
        )
        try:
            decision = await provider.aauthorize(request)
            if not isinstance(decision, AuthzDecision):
                raise TypeError("AuthorizationProvider.aauthorize must return AuthzDecision")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "Authorization provider failed while evaluating route permission %s",
                permission,
                exc_info=True,
            )
            return permission if not config.fail_closed else None
        return permission if decision.allow else None

    results = await asyncio.gather(*[_evaluate(p) for p in _ALL_PERMISSIONS])
    return [p for p in results if p is not None]


async def resolve_route_permissions_for_request(request: Request, user: Any) -> list[str]:
    """Resolve the effective route permissions for a request's authenticated user.

    Public wrapper pairing ``resolve_route_permissions`` with the internal-caller
    heuristics of ``_is_internal_caller`` (auth source, synthetic internal role,
    internal auth header), so middleware-less consumers resolve exactly what
    ``_authenticate`` resolves and the two cannot drift apart.
    """
    return await resolve_route_permissions(user, is_internal=_is_internal_caller(request, user))


def role_has_policy(role: str) -> bool:
    """Whether *role* has a policy block, so assigning it cannot lock the user out.

    False only when RBAC is enabled and certain to treat *role* as undefined (it
    would then fail closed on every check). A disabled or unresolvable provider
    answers True: there is no role table to be missing from.
    """
    config = _get_route_authorization_config()
    if config.enabled is not True:
        return True
    try:
        provider = _get_cached_route_provider(config)
    except Exception:
        return True
    validate_role = getattr(provider, "validate_role", None)
    if validate_role is None:
        return True
    try:
        validate_role(role)
    except ValueError:
        return False
    return True


class _AuthorizationUnavailable(Exception):
    """Raised internally when the provider cannot be resolved for a route check.

    Carries the ``fail_closed`` flag so the caller can decide between deny-all
    and legacy allow-all without re-reading config.
    """

    def __init__(self, *, fail_closed: bool) -> None:
        self.fail_closed = fail_closed


def _resolve_route_scoped_authorization(user: User, *, is_internal: bool) -> tuple[AuthorizationProvider | None, Principal | None]:
    """Return ``(provider, principal)`` for route-level resource authorization.

    When authorization is disabled, returns ``(None, None)`` so callers can
    short-circuit to legacy behavior (resource visible). When enabled,
    resolves the cached provider and builds a Principal identical to
    ``resolve_route_permissions`` (including the ``INTERNAL_SYSTEM_ROLE``
    → ``None`` pop so internal callers fall under ``default_role``).

    Raises ``_AuthorizationUnavailable`` (carrying the ``fail_closed`` flag)
    when the provider cannot be resolved; callers translate that into the
    appropriate deny response (empty list / 403).
    """
    config = _get_route_authorization_config()
    if config.enabled is not True:
        return None, None

    try:
        provider = _get_cached_route_provider(config)
        if provider is None:
            raise ValueError("authorization is enabled but provider resolution returned None")
    except Exception:
        logger.warning("Failed to resolve authorization provider for route-level resources", exc_info=True)
        raise _AuthorizationUnavailable(fail_closed=config.fail_closed)

    principal = build_principal_from_context(
        _route_authz_context(user, is_internal=is_internal),
        default_role=config.default_role,
    )
    return provider, principal


def resolve_model_authorization(user: User, *, is_internal: bool) -> tuple[AuthorizationProvider | None, Principal | None]:
    """Return ``(provider, principal)`` for model-route authorization.

    Delegates to ``_resolve_route_scoped_authorization``: disabled →
    ``(None, None)``; provider-resolution failure raises
    ``_AuthorizationUnavailable`` (carrying ``fail_closed``).
    """
    return _resolve_route_scoped_authorization(user, is_internal=is_internal)


def model_use_allowed(user: User, model_name: str, *, is_internal: bool, fail_closed: bool) -> bool:
    """Whether *user*'s role may ``use`` *model_name* (``authorize("model", "use")``).

    Disabled authorization allows. A provider that cannot be resolved or that
    raises answers ``not fail_closed``. Shared by ``GET /api/models/{name}`` and
    the built-in-agent visibility checks so they can never disagree.
    """
    try:
        provider, principal = resolve_model_authorization(user, is_internal=is_internal)
    except _AuthorizationUnavailable:
        return not fail_closed
    if provider is None or principal is None:
        return True
    try:
        decision = provider.authorize(AuthzRequest(principal=principal, resource="model", action="use", target=model_name))
        if not isinstance(decision, AuthzDecision):
            raise TypeError("AuthorizationProvider.authorize must return AuthzDecision")
        return decision.allow
    except Exception:
        logger.warning("Authorization provider failed while checking model:use for %s", model_name, exc_info=True)
        return not fail_closed


def resolve_skill_authorization(user: User, *, is_internal: bool) -> tuple[AuthorizationProvider | None, Principal | None]:
    """Return ``(provider, principal)`` for skill-route authorization.

    Same resolution and Principal construction as ``resolve_model_authorization``
    (disabled → ``(None, None)``; provider-resolution failure raises
    ``_AuthorizationUnavailable`` carrying ``fail_closed``). Consumers translate
    that into the appropriate deny response (empty skill listing).
    """
    return _resolve_route_scoped_authorization(user, is_internal=is_internal)


def _route_authz_context(user: User, *, is_internal: bool) -> dict:
    """Build the shared Principal context dict for a request-scoped user.

    Applies the ``INTERNAL_SYSTEM_ROLE → None`` pop so internal callers fall
    under ``default_role`` (mirrors ``inject_authenticated_user_context``).
    Used by ``_resolve_route_scoped_authorization`` (model/skill routes) and
    ``authorize_sandbox_for_request`` so every route-level authorization path
    builds the identity the same way.
    """
    from app.gateway.internal_auth import INTERNAL_SYSTEM_ROLE

    user_role = getattr(user, "system_role", None)
    if user_role == INTERNAL_SYSTEM_ROLE:
        user_role = None
    return {
        "user_id": str(user.id),
        "user_role": user_role,
        "oauth_provider": getattr(user, "oauth_provider", None),
        "oauth_id": getattr(user, "oauth_id", None),
        "is_internal": is_internal,
    }


def authorize_sandbox_for_request(
    user: User,
    *,
    is_internal: bool,
    app_config: AppConfig | None,
) -> None:
    """Check ``sandbox:execute`` for a Gateway request before sandbox acquisition.

    Thin wrapper over the harness-level ``authorize_sandbox_execution`` that
    builds the Principal from the request-scoped ``user`` — the same identity
    construction as ``resolve_model_authorization`` (including the
    ``INTERNAL_SYSTEM_ROLE → None`` pop). Raises
    :class:`~deerflow.sandbox.exceptions.SandboxAuthorizationError` on deny or
    on provider-resolution failure under ``fail_closed``; callers translate
    that into skipping the sandbox sync (not an HTTP error, since the primary
    operation — e.g. file upload — can proceed without it).

    No-op when ``authorization.enabled`` is false.
    """
    from deerflow.authz.sandbox_authz import authorize_sandbox_execution
    from deerflow.sandbox.exceptions import SandboxAuthorizationError

    config = _get_route_authorization_config()
    if config.enabled is not True:
        return

    context = _route_authz_context(user, is_internal=is_internal)

    try:
        authorize_sandbox_execution(
            context=context,
            app_config=app_config,
        )
    except SandboxAuthorizationError:
        raise
    except Exception:
        # Defense-in-depth: provider resolution and authorize() errors are
        # already converted to SandboxAuthorizationError (or allowed under
        # fail-open) one layer down inside authorize_sandbox_execution, so this
        # normally only catches config-read failures here (e.g. get_config()
        # raising in a config-less environment). Those must not 500 the
        # upload/artifact route — degrade per fail_closed instead.
        logger.warning("Failed to resolve authorization provider for sandbox:execute", exc_info=True)
        if config.fail_closed:
            raise SandboxAuthorizationError(role=context.get("user_role")) from None


@dataclass(slots=True)
class SandboxRequestLease:
    """One Gateway request's process-local use of a sandbox client."""

    sandbox: object | None
    sandbox_id: str | None
    denied: bool
    owner_id: str | None
    provider: object | None

    async def release(self) -> None:
        """Drop the request holder without bypassing concurrent executions."""
        if self.owner_id is None or self.provider is None:
            return
        from deerflow.sandbox.lease import get_sandbox_lease_manager

        owner_id = self.owner_id
        self.owner_id = None
        await get_sandbox_lease_manager(self.provider).release_async(owner_id)


async def try_acquire_sandbox_for_request(
    request: Request,
    sandbox_provider,
    thread_id: str,
    *,
    user_id: str,
    app_config: AppConfig | None,
    owner_prefix: str = "gateway",
    release_on_last: bool = True,
) -> SandboxRequestLease:
    """Gate + acquire the thread sandbox for a Gateway sync path.

    Single entry point for the uploads/artifacts sandbox-sync paths so the
    deny/skip semantics live in one place: runs the ``sandbox:execute`` gate
    for the request's user, then acquires the sandbox under a unique request
    holder. Callers must await :meth:`SandboxRequestLease.release` after their
    last client operation.

    - denied role → no sandbox/owner and ``denied=True``: acquisition was skipped by policy;
      the primary operation (upload / artifact edit) proceeds without the
      sandbox copy.
    - allowed → ``sandbox`` is the acquired instance, or ``sandbox is None`` when
      the provider lost it right after acquiring (infrastructure error —
      callers surface it as 500 / RuntimeError respectively, since that is
      not a policy decision).
    - ``request is None`` (direct-call tests) and unresolvable users skip the
      gate — same fail-open semantics as the models routes' anonymous bypass.
    """
    from deerflow.sandbox.exceptions import SandboxAuthorizationError

    try:
        from app.gateway.deps import get_optional_user_from_request

        user = await get_optional_user_from_request(request) if request is not None else None
        if user is not None:
            authorize_sandbox_for_request(user, is_internal=_is_internal_caller(request, user), app_config=app_config)
    except SandboxAuthorizationError:
        logger.info("Sandbox sync skipped: sandbox execution not permitted for this caller (thread_id=%s)", thread_id)
        return SandboxRequestLease(
            sandbox=None,
            sandbox_id=None,
            denied=True,
            owner_id=None,
            provider=None,
        )

    from deerflow.sandbox.lease import get_sandbox_lease_manager

    owner_id = f"{owner_prefix}:{uuid.uuid4()}"
    sandbox_id = await get_sandbox_lease_manager(sandbox_provider).acquire_async(
        owner_id,
        thread_id,
        user_id=user_id,
        release_on_last=release_on_last,
    )
    return SandboxRequestLease(
        sandbox=sandbox_provider.get(sandbox_id),
        sandbox_id=sandbox_id,
        denied=False,
        owner_id=owner_id,
        provider=sandbox_provider,
    )


async def _authenticate(request: Request) -> AuthContext:
    """Authenticate request and return AuthContext.

    Delegates to deps.get_optional_user_from_request() for the JWT→User pipeline.
    Returns AuthContext with user=None for anonymous requests.
    """
    from app.gateway.deps import get_optional_user_from_request

    user = await get_optional_user_from_request(request)
    if user is None:
        return AuthContext(user=None, permissions=[])

    permissions = await resolve_route_permissions_for_request(request, user)
    return AuthContext(user=user, permissions=permissions)


def _is_internal_caller(request: Request, user: Any) -> bool:
    """Determine if the request originates from a trusted internal caller.

    Checks three signals (any one suffices):
    1. ``request.state.auth_source == AUTH_SOURCE_INTERNAL`` (set by AuthMiddleware).
    2. ``user.system_role == INTERNAL_SYSTEM_ROLE`` (synthetic internal user).
    3. The request carries a valid internal auth token header (decorator-only path
       where AuthMiddleware may not have stamped ``auth_source`` yet).
    """
    from app.gateway.auth_disabled import AUTH_SOURCE_INTERNAL
    from app.gateway.internal_auth import INTERNAL_AUTH_HEADER_NAME, INTERNAL_SYSTEM_ROLE, is_valid_internal_auth_token

    if getattr(getattr(request, "state", None), "auth_source", None) == AUTH_SOURCE_INTERNAL:
        return True
    if getattr(user, "system_role", None) == INTERNAL_SYSTEM_ROLE:
        return True
    # Decorator-only path: check the internal token header directly.
    internal_token = request.headers.get(INTERNAL_AUTH_HEADER_NAME) if hasattr(request, "headers") else None
    if internal_token and is_valid_internal_auth_token(internal_token):
        return True
    return False


def require_auth[**P, T](func: Callable[P, T]) -> Callable[P, T]:
    """Decorator that authenticates the request and enforces authentication.

    Independently raises HTTP 401 for unauthenticated requests, regardless of
    whether ``AuthMiddleware`` is present in the ASGI stack. Sets the resolved
    ``AuthContext`` on ``request.state.auth`` for downstream handlers.

    Must be placed ABOVE other decorators (executes after them).

    Usage:
        @router.get("/{thread_id}")
        @require_auth  # Bottom decorator (executes first after permission check)
        @require_permission("threads", "read")
        async def get_thread(thread_id: str, request: Request):
            auth: AuthContext = request.state.auth
            ...

    Raises:
        HTTPException: 401 if the request is unauthenticated.
        ValueError: If 'request' parameter is missing.
    """

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        request = kwargs.get("request")
        if request is None:
            # Unit tests may call decorated handlers directly without a
            # FastAPI Request object. Inject a minimal request stub when
            # the wrapped function declares `request`.
            if "request" in inspect.signature(func).parameters:
                kwargs["request"] = _make_test_request_stub()
            else:
                raise ValueError("require_auth decorator requires 'request' parameter")
            request = kwargs["request"]

        if getattr(request, "_deerflow_test_bypass_auth", False):
            return await func(*args, **kwargs)

        # Authenticate and set context
        auth_context = await _authenticate(request)
        request.state.auth = auth_context

        if not auth_context.is_authenticated:
            raise HTTPException(status_code=401, detail="Authentication required")

        return await func(*args, **kwargs)

    return wrapper


def require_permission(
    resource: str,
    action: str,
    owner_check: bool = False,
    require_existing: bool = False,
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """Decorator that checks permission for resource:action.

    Must be used AFTER @require_auth.

    Args:
        resource: Resource name (e.g., "threads", "runs")
        action: Action name (e.g., "read", "write", "delete")
        owner_check: If True, validates that the current user owns the resource.
                     Requires 'thread_id' path parameter and performs ownership check.
        require_existing: Only meaningful with ``owner_check=True``. If True, a
                          missing ``threads_meta`` row counts as a denial (404)
                          instead of "untracked legacy thread, allow". Use on
                          **destructive / mutating** routes (DELETE, PATCH,
                          state-update) so a deleted thread can't be re-targeted
                          by another user via the missing-row code path.

    Usage:
        # Read-style: legacy untracked threads are allowed
        @require_permission("threads", "read", owner_check=True)
        async def get_thread(thread_id: str, request: Request):
            ...

        # Destructive: thread row MUST exist and be owned by caller
        @require_permission("threads", "delete", owner_check=True, require_existing=True)
        async def delete_thread(thread_id: str, request: Request):
            ...

    Raises:
        HTTPException 401: If authentication required but user is anonymous
        HTTPException 403: If user lacks permission
        HTTPException 404: If owner_check=True but user doesn't own the thread
        ValueError: If owner_check=True but 'thread_id' parameter is missing
    """

    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            request = kwargs.get("request")
            if request is None:
                # Unit tests may call decorated route handlers directly — with
                # or without constructing a FastAPI Request object — and may
                # pass ``request`` positionally. Bind to the real signature
                # first so a positional request is found rather than
                # duplicated by the stub injection below.
                try:
                    bound = inspect.signature(func).bind_partial(*args, **kwargs)
                except TypeError:
                    bound = None
                if bound is not None and "request" in bound.arguments:
                    request = bound.arguments["request"]
                elif "request" in inspect.signature(func).parameters:
                    kwargs["request"] = _make_test_request_stub()
                    request = kwargs["request"]
                else:
                    return await func(*args, **kwargs)

            if getattr(request, "_deerflow_test_bypass_auth", False):
                return await func(*args, **kwargs)

            auth: AuthContext = getattr(request.state, "auth", None)
            if auth is None:
                auth = await _authenticate(request)
                request.state.auth = auth

            if not auth.is_authenticated:
                raise HTTPException(status_code=401, detail="Authentication required")

            # Check permission
            if not auth.has_permission(resource, action):
                raise HTTPException(
                    status_code=403,
                    detail=f"Permission denied: {resource}:{action}",
                )

            # Owner check for thread-specific resources.
            #
            # 2.0-rc moved thread metadata into the SQL persistence layer
            # (``threads_meta`` table). We verify ownership via
            # ``ThreadMetaStore.check_access``: it returns True for
            # missing rows (untracked legacy thread) and for rows whose
            # ``user_id`` is NULL (shared / pre-auth data), so this is
            # strict-deny rather than strict-allow — only an *existing*
            # row with a *different* user_id triggers 404.
            if owner_check:
                thread_id = kwargs.get("thread_id")
                if thread_id is None:
                    raise ValueError("require_permission with owner_check=True requires 'thread_id' parameter")

                from app.gateway.deps import get_thread_store

                thread_store = get_thread_store(request)
                # Internal callers get no owner-header fallback: AuthMiddleware
                # already stamped a delegated caller's storage principal here,
                # and an undelegated one never reaches a route.
                storage_user_id = auth.storage_user_id or str(auth.user.id)
                allowed = await thread_store.check_access(
                    thread_id,
                    storage_user_id,
                    require_existing=require_existing,
                )
                if not allowed:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Thread {thread_id} not found",
                    )

            return await func(*args, **kwargs)

        return wrapper

    return decorator


def resource_permission_dependency(resource: str):
    """Enforce HTTP read/write/delete scopes for request-free CRUD handlers.

    Router dependencies run with the real HTTP request even when a handler's
    ``request`` parameter is its Pydantic body. Reuse the normal authorization
    check rather than treating route admission as a grant of every action.
    """
    checks = {}
    for action in ("read", "write", "delete"):

        async def permitted(request: Request) -> None:
            return None

        checks[action] = require_permission(resource, action)(permitted)

    async def dependency(request: Request) -> None:
        action = "read" if request.method in ("GET", "HEAD", "OPTIONS") else "delete" if request.method == "DELETE" else "write"
        await checks[action](request=request)

    return dependency


def require_entitlement(
    key: str,
    *,
    requested_amount: int = 1,
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """Decorator enforcing the M4 entitlement gate for a paid mutation.

    Design: ``docs/momo-week/m4-entitlement.md`` §3, §7.3 (task ``c2``/``e6``).
    Must be composed AFTER ``@require_permission`` (i.e. placed BELOW it in
    the decorator stack, so it executes second) — it reads
    ``request.state.auth.organization_id``, which only ``AuthMiddleware`` or
    ``require_permission``'s own ``_authenticate()`` populate. No router in
    this codebase uses ``@require_auth`` today, and stacking it back in above
    this decorator would wipe that org context right before it's needed.

    Only suitable for a gate key (no attempted-count needed). A limit key
    (``projects.max`` etc.) needs the caller's live usage count from the
    request body, so those routes call ``evaluate_entitlement(...)`` inline
    in the handler instead — the same "decorator for the common case, inline
    call for the parametrized case" split ``board.py`` already uses for
    ``_require_client_access``.

    Raises:
        HTTPException 401: If unauthenticated.
        HTTPException 403: If entitlements are enabled and the key is denied
            (no resolved organization, no row, or a suspended row). The body
            is ``{"error": "entitlement_exceeded", "key": ..., "reason": ...}``
            so the frontend can show upgrade copy instead of a bare
            permission error.
    """

    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            request = kwargs.get("request")
            if request is None:
                try:
                    bound = inspect.signature(func).bind_partial(*args, **kwargs)
                except TypeError:
                    bound = None
                if bound is not None and "request" in bound.arguments:
                    request = bound.arguments["request"]
                elif "request" in inspect.signature(func).parameters:
                    kwargs["request"] = _make_test_request_stub()
                    request = kwargs["request"]
                else:
                    return await func(*args, **kwargs)

            if getattr(request, "_deerflow_test_bypass_auth", False):
                return await func(*args, **kwargs)

            from deerflow.config.entitlement_config import resolve_current_entitlement_config

            entitlement_config = resolve_current_entitlement_config()
            if not entitlement_config.enabled:
                return await func(*args, **kwargs)

            auth: AuthContext | None = getattr(request.state, "auth", None)
            if auth is None:
                auth = await _authenticate(request)
                request.state.auth = auth

            if not auth.is_authenticated:
                raise HTTPException(status_code=401, detail="Authentication required")

            from app.gateway.deps import get_entitlement_repo
            from deerflow.authz.entitlements import evaluate_entitlement

            repo = get_entitlement_repo(request)
            decision = await evaluate_entitlement(
                repo,
                auth.organization_id,
                key,
                requested_amount=requested_amount,
                config=entitlement_config,
            )
            if not decision.allowed:
                raise HTTPException(
                    status_code=403,
                    detail={"error": "entitlement_exceeded", "key": key, "reason": decision.reason},
                )

            return await func(*args, **kwargs)

        return wrapper

    return decorator
````

## backend/packages/harness/deerflow/runtime/user_context.py

````python
"""Request-scoped user context for user-based authorization.

This module holds a :class:`~contextvars.ContextVar` that the gateway's
auth middleware sets after a successful authentication. Repository
methods read the contextvar via a sentinel default parameter, letting
routers stay free of ``user_id`` boilerplate.

Three-state semantics for the repository ``user_id`` parameter (the
consumer side of this module lives in ``deerflow.persistence.*``):

- ``_AUTO`` (module-private sentinel, default): read from contextvar;
  raise :class:`RuntimeError` if unset.
- Explicit ``str``: use the provided value, overriding contextvar.
- Explicit ``None``: no WHERE clause — used only by migration scripts
  and admin CLIs that intentionally bypass isolation.

Dependency direction
--------------------
``persistence`` (lower layer) reads from this module; ``gateway.auth``
(higher layer) writes to it. ``CurrentUser`` is defined here as a
:class:`typing.Protocol` so that ``persistence`` never needs to import
the concrete ``User`` class from ``gateway.auth.models``. Any object
with an ``.id: str`` attribute structurally satisfies the protocol.

Asyncio semantics
-----------------
``ContextVar`` is task-local under asyncio, not thread-local. Each
FastAPI request runs in its own task, so the context is naturally
isolated. ``asyncio.create_task`` and ``asyncio.to_thread`` inherit the
parent task's context, which is typically the intended behaviour; if
a background task must *not* see the foreground user, wrap it with
``contextvars.copy_context()`` to get a clean copy.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Final, Protocol, runtime_checkable


@runtime_checkable
class CurrentUser(Protocol):
    """Structural type for the current authenticated user.

    Any object with an ``.id: str`` attribute satisfies this protocol.
    Concrete implementations live in ``app.gateway.auth.models.User``.
    """

    id: str


_current_user: Final[ContextVar[CurrentUser | None]] = ContextVar("deerflow_current_user", default=None)

# The Gateway stamps these fields after authentication.  The marker is an
# in-process capability: it lets the run worker distinguish the values that
# were written by ``inject_authenticated_user_context`` from a caller's
# ordinary ``RunnableConfig.context`` without persisting a secret or relying
# on a user-controlled boolean.  The worker consumes and removes the marker
# before exposing ``ToolRuntime.context``.
AUTHENTICATED_CONTEXT_MARKER_KEY: Final[str] = "__deerflow_authenticated_context"
AUTHENTICATED_CONTEXT_MARKER: Final[object] = object()

# Keep the private-session capability in this dependency-light auth context.
# Run bootstrap must not import MCP/tool assembly while repositories initialize.
PRIVATE_MCP_SESSION_CONTEXT_KEY: Final[str] = "__deerflow_private_mcp_session"
PRIVATE_MCP_SESSION_MARKER: Final[object] = object()

WORKSPACE_IDENTITY_CONTEXT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "actor_user_id",
        "storage_user_id",
        "organization_id",
        "organization_role",
    }
)


@dataclass(frozen=True, slots=True)
class WorkspaceStorageContext:
    """Server-selected workspace identity for shared resource storage.

    ``actor_user_id`` is the authenticated human. ``storage_user_id`` is the
    owner bucket used by repositories and filesystem paths; it equals the
    actor for private organizations and is a dedicated non-login principal for
    shared workspaces. The two identities must not be conflated.
    """

    actor_user_id: str
    organization_id: str | None
    storage_user_id: str
    role: str | None = None


StorageContext = WorkspaceStorageContext
_storage_context: Final[ContextVar[WorkspaceStorageContext | None]] = ContextVar("deerflow_storage_context", default=None)


def set_current_user(user: CurrentUser) -> Token[CurrentUser | None]:
    """Set the current user for this async task.

    Returns a reset token that should be passed to
    :func:`reset_current_user` in a ``finally`` block to restore the
    previous context.
    """
    return _current_user.set(user)


def reset_current_user(token: Token[CurrentUser | None]) -> None:
    """Restore the context to the state captured by ``token``."""
    _current_user.reset(token)


def get_current_user() -> CurrentUser | None:
    """Return the current user, or ``None`` if unset.

    Safe to call in any context. Used by code paths that can proceed
    without a user (e.g. migration scripts, public endpoints).
    """
    return _current_user.get()


def set_storage_context(context: WorkspaceStorageContext) -> Token[WorkspaceStorageContext | None]:
    """Set the server-validated workspace storage identity for this task."""

    if not context.actor_user_id or not context.storage_user_id:
        raise ValueError("workspace storage context requires actor and storage user ids")
    return _storage_context.set(context)


def reset_storage_context(token: Token[WorkspaceStorageContext | None]) -> None:
    """Restore the previous workspace storage context."""

    _storage_context.reset(token)


def get_storage_context() -> WorkspaceStorageContext | None:
    """Return the server-validated workspace context, if one is active."""

    return _storage_context.get()


def get_workspace_actor_user_id() -> str | None:
    """Return the authenticated actor id without changing storage scoping."""

    context = _storage_context.get()
    if context is not None:
        return context.actor_user_id
    user = _current_user.get()
    return str(user.id) if user is not None else None


def require_current_user() -> CurrentUser:
    """Return the current user, or raise :class:`RuntimeError`.

    Used by repository code that must not be called outside a
    request-authenticated context. The error message is phrased so
    that a caller debugging a stack trace can locate the offending
    code path.
    """
    user = _current_user.get()
    if user is None:
        raise RuntimeError("repository accessed without user context")
    return user


# ---------------------------------------------------------------------------
# Effective user_id helpers (filesystem isolation)
# ---------------------------------------------------------------------------

DEFAULT_USER_ID: Final[str] = "default"


def get_effective_user_id() -> str:
    """Return the active storage principal, or DEFAULT_USER_ID if unset.

    Unlike :func:`require_current_user` this never raises — it is designed
    for filesystem-path resolution where a valid user bucket is always needed.
    A shared workspace supplies its dedicated principal; private requests fall
    back to the authenticated actor for backwards compatibility.
    """
    context = _storage_context.get()
    if context is not None:
        return context.storage_user_id
    user = _current_user.get()
    if user is None:
        return DEFAULT_USER_ID
    return str(user.id)


def get_effective_storage_user_id() -> str:
    """Explicit spelling for callers that need the workspace storage bucket."""

    return get_effective_user_id()


def get_effective_actor_user_id() -> str:
    """Return the authenticated actor id, with the legacy default fallback."""

    return get_workspace_actor_user_id() or DEFAULT_USER_ID


def resolve_organization_id() -> str | None:
    """Return the request's server-resolved active organization, if any.

    Only ``AuthMiddleware`` sets it, after proving the session or PAT caller's
    active membership, so no request field can choose it. ``None`` (internal
    callers, auth-disabled mode, work outside a request) means no organization
    boundary was established: keep the user filter and add no organization
    filter.
    """
    context = _storage_context.get()
    return context.organization_id if context is not None else None


def _storage_user_id_from_auth_identity(identity: object | None) -> str | None:
    """Return a stable storage-safe ID for a LangGraph auth identity."""
    if not isinstance(identity, str) or not identity:
        return None

    # LangGraph permits arbitrary strings (commonly email addresses) for
    # BaseUser.identity, while DeerFlow's user directories require a narrower
    # charset. Keep the normalization at the auth boundary so graph
    # construction and runtime middleware always select the same bucket.
    from deerflow.config.paths import make_safe_user_id

    return make_safe_user_id(identity)


def _user_id_from_auth_user(user: object | None) -> str | None:
    if isinstance(user, Mapping):
        identity = user.get("identity")
    else:
        identity = getattr(user, "identity", None)
    return _storage_user_id_from_auth_identity(identity)


def _user_id_from_langgraph_config(config: object | None) -> str | None:
    if not isinstance(config, Mapping):
        return None
    configurable = config.get("configurable")
    if not isinstance(configurable, Mapping):
        return None

    user_id = _storage_user_id_from_auth_identity(configurable.get("langgraph_auth_user_id"))
    if user_id:
        return user_id
    return _user_id_from_auth_user(configurable.get("langgraph_auth_user"))


def resolve_config_user_id(config: object | None) -> str:
    """Resolve the effective user from a LangGraph/Gateway run config.

    Server-owned LangGraph authentication fields take precedence over ordinary
    ``user_id`` values because Agent Server reserves and overwrites the auth
    fields, while a standalone client may supply regular configurable/context
    values. Gateway runtime context remains the next source for DeerFlow's
    embedded run path, followed by the legacy configurable channel and the
    request ContextVar/default fallback.
    """
    # Gateway-injected storage identity is server-owned and must win over the
    # authenticated actor when a selected shared workspace is active.  The
    # in-process marker prevents an arbitrary standalone RunnableConfig from
    # selecting another workspace by naming ``storage_user_id`` directly.
    if isinstance(config, Mapping):
        context = config.get("context")
        if isinstance(context, Mapping):
            storage_user_id = context.get("storage_user_id")
            if storage_user_id:
                if context.get(AUTHENTICATED_CONTEXT_MARKER_KEY) is AUTHENTICATED_CONTEXT_MARKER:
                    return str(storage_user_id)
                # Once the worker consumes the in-process marker, the
                # middleware's task-local storage context remains the trusted
                # proof for this live run.  Do not infer trust from a caller's
                # actor/org fields; those are ordinary mapping values.
                active_storage = _storage_context.get()
                if active_storage is not None and active_storage.storage_user_id == str(storage_user_id):
                    return str(storage_user_id)

    langgraph_user_id = _user_id_from_langgraph_config(config)
    if langgraph_user_id:
        return langgraph_user_id

    if isinstance(config, Mapping):
        context = config.get("context")
        if isinstance(context, Mapping):
            context_user_id = context.get("user_id")
            if context_user_id:
                return str(context_user_id)

        configurable = config.get("configurable")
        if isinstance(configurable, Mapping):
            configurable_user_id = configurable.get("user_id")
            if configurable_user_id:
                return str(configurable_user_id)

    return get_effective_user_id()


def resolve_runtime_user_id(runtime: object | None) -> str:
    """Single source of truth for a tool/middleware's effective user_id.

    Resolution order (most authoritative first):
      1. server-owned ``runtime.context["storage_user_id"]`` from the Gateway
         workspace selector.
      2. ``runtime.server_info.user.identity`` — populated by current LangGraph
         runtimes from Agent Server's authenticated user. Unlike ordinary run
         context, this is server-owned.
      3. ``config["configurable"]["langgraph_auth_user_id"]`` — populated by
         LangGraph Server from the deployment's ``@auth.authenticate`` result.
         This supports older runtimes and code paths without ``server_info``.
      4. ``runtime.context["user_id"]`` — legacy Gateway identity when no
         workspace storage principal was selected.
      5. The workspace ContextVar, then
         ``_current_user`` — set by the auth middleware at request entry.
      6. ``DEFAULT_USER_ID`` — last-resort fallback.

    ``actor_user_id`` is carried beside this value for credential-sensitive
    consumers; use :func:`resolve_runtime_actor_user_id` there.

    The storage identity survives boundaries where the contextvar may have
    been lost (background tasks scheduled outside the request task, worker
    pools, and future cross-process drivers).
    """
    server_info = getattr(runtime, "server_info", None)
    server_user_id = _user_id_from_auth_user(getattr(server_info, "user", None))
    if server_user_id:
        return server_user_id

    langgraph_user_id = _user_id_from_langgraph_auth()
    if langgraph_user_id:
        return langgraph_user_id

    context = getattr(runtime, "context", None)
    if isinstance(context, Mapping):
        storage_user_id = context.get("storage_user_id")
        if storage_user_id:
            return str(storage_user_id)
    active_storage = _storage_context.get()
    if active_storage is not None:
        return active_storage.storage_user_id

    if isinstance(context, Mapping):
        ctx_user_id = context.get("user_id")
        if ctx_user_id:
            return str(ctx_user_id)
    return get_effective_user_id()


def resolve_runtime_actor_user_id(runtime: object | None) -> str:
    """Resolve the authenticated actor for credentials and audit attribution."""
    server_info = getattr(runtime, "server_info", None)
    server_user_id = _user_id_from_auth_user(getattr(server_info, "user", None))
    if server_user_id:
        return server_user_id

    langgraph_user_id = _user_id_from_langgraph_auth()
    if langgraph_user_id:
        return langgraph_user_id

    context = getattr(runtime, "context", None)
    if isinstance(context, Mapping):
        actor_user_id = context.get("actor_user_id")
        if actor_user_id:
            return str(actor_user_id)

    if isinstance(context, Mapping):
        ctx_user_id = context.get("user_id")
        if ctx_user_id:
            return str(ctx_user_id)
    return get_effective_actor_user_id()


def _user_id_from_langgraph_auth() -> str | None:
    """Return the authenticated LangGraph Server user id, if available.

    LangGraph Server reserves the ``langgraph_auth_user`` and
    ``langgraph_auth_user_id`` configurable keys and populates them from the
    deployment's ``@auth.authenticate`` result. ``get_config()`` raises when
    called outside a runnable context, which simply means this identity channel
    is unavailable.
    """
    try:
        from langgraph.config import get_config

        config = get_config()
    except RuntimeError:
        return None

    return _user_id_from_langgraph_config(config)


# ---------------------------------------------------------------------------
# Sentinel-based user_id resolution
# ---------------------------------------------------------------------------
#
# Repository methods accept a ``user_id`` keyword-only argument that
# defaults to ``AUTO``. The three possible values drive distinct
# behaviours; see the docstring on :func:`resolve_user_id`.


class _AutoSentinel:
    """Singleton marker meaning 'resolve user_id from contextvar'."""

    _instance: _AutoSentinel | None = None

    def __new__(cls) -> _AutoSentinel:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "<AUTO>"


AUTO: Final[_AutoSentinel] = _AutoSentinel()


def resolve_user_id(
    value: str | None | _AutoSentinel,
    *,
    method_name: str = "repository method",
) -> str | None:
    """Resolve the user_id parameter passed to a repository method.

    Three-state semantics:

    - :data:`AUTO` (default): read from contextvar; raise
      :class:`RuntimeError` if no user is in context. This is the
      common case for request-scoped calls.
    - Explicit ``str``: use the provided id verbatim, overriding any
      contextvar value. Useful for tests and admin-override flows.
    - Explicit ``None``: no filter — the repository should skip the
      user_id WHERE clause entirely. Reserved for migration scripts
      and CLI tools that intentionally bypass isolation.
    """
    if isinstance(value, _AutoSentinel):
        storage_context = _storage_context.get()
        if storage_context is not None:
            return storage_context.storage_user_id
        user = _current_user.get()
        if user is None:
            raise RuntimeError(f"{method_name} called with user_id=AUTO but no user context is set; pass an explicit user_id, set the contextvar via auth middleware, or opt out with user_id=None for migration/CLI paths.")
        # Coerce to ``str`` at the boundary: ``User.id`` is typed as
        # ``UUID`` for the API surface, but the persistence layer
        # stores ``user_id`` as ``String(64)`` and aiosqlite cannot
        # bind a raw UUID object to a VARCHAR column ("type 'UUID' is
        # not supported"). Honour the documented return type here
        # rather than ripple a type change through every caller.
        return str(user.id)
    return value
````
