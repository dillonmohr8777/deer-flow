"""Shared workspace listing, creation, and selection."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.gateway.auth_disabled import AUTH_SOURCE_SESSION
from app.gateway.auth_middleware import WORKSPACE_COOKIE_NAME
from app.gateway.csrf_middleware import is_secure_request
from deerflow.persistence.engine import get_session_factory
from deerflow.persistence.organizations.identity import private_organization_id, private_organization_slug
from deerflow.persistence.organizations.model import OrganizationMemberRow, OrganizationRow
from deerflow.persistence.organizations.resolution import active_organization_for_user
from deerflow.persistence.user.model import UserRow

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


class WorkspaceSummary(BaseModel):
    id: str
    name: str
    role: str


class WorkspaceListResponse(BaseModel):
    workspaces: list[WorkspaceSummary]
    active_workspace_id: str | None = None


class WorkspaceCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=256)


class WorkspaceCreateResponse(WorkspaceSummary):
    pass


class WorkspaceSelectRequest(BaseModel):
    workspace_id: str | None = Field(default=None, max_length=64)


class WorkspaceSelectResponse(BaseModel):
    active_workspace_id: str | None = None


def _session_factory():
    session_factory = get_session_factory()
    if session_factory is None:
        raise HTTPException(status_code=503, detail="Workspace persistence is unavailable")
    return session_factory


def _session_actor(request: Request):
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    if getattr(request.state, "auth_source", None) != AUTH_SOURCE_SESSION:
        raise HTTPException(status_code=403, detail="Browser session required")
    return user


def _set_workspace_cookie(response: Response, request: Request, organization_id: str | None) -> None:
    secure = is_secure_request(request)
    if organization_id is None:
        response.delete_cookie(WORKSPACE_COOKIE_NAME, secure=secure, samesite="lax")
        return
    response.set_cookie(
        key=WORKSPACE_COOKIE_NAME,
        value=organization_id,
        httponly=True,
        secure=secure,
        samesite="lax",
    )


async def _active_memberships(session, user_id: str) -> list[tuple[OrganizationRow, str]]:
    result = await session.execute(
        select(OrganizationRow, OrganizationMemberRow.role)
        .join(
            OrganizationMemberRow,
            (OrganizationMemberRow.organization_id == OrganizationRow.id)
            & (OrganizationMemberRow.user_id == user_id),
        )
        .where(
            OrganizationRow.status == "active",
            OrganizationMemberRow.status == "active",
        )
        .order_by(OrganizationRow.created_at.asc(), OrganizationRow.id.asc())
    )
    return [(organization, str(role)) for organization, role in result.all()]


@router.get("", response_model=WorkspaceListResponse)
async def list_workspaces(request: Request) -> WorkspaceListResponse:
    actor = _session_actor(request)
    actor_id = str(actor.id)
    async with _session_factory()() as session:
        memberships = await _active_memberships(session, actor_id)

    private_id = private_organization_id(actor_id)
    # The private organization is always represented by the explicit
    # "My private workspace" option in the client.  Returning it here would
    # duplicate that option and expose an implementation slug, so this list
    # is intentionally limited to shared organizations.
    workspaces = [
        WorkspaceSummary(
            id=organization.id,
            name=organization.name,
            role=role,
        )
        for organization, role in memberships
        if organization.storage_user_id is not None
    ]
    if not any(organization.id == private_id for organization, _role in memberships):
        # AuthMiddleware already requires this membership for a normal browser
        # request, but retaining the guard keeps the endpoint fail-closed in a
        # middleware-less test composition.
        raise HTTPException(status_code=403, detail="Active organization membership required")

    selected_id = request.cookies.get(WORKSPACE_COOKIE_NAME)
    selected_id = selected_id.strip() if selected_id and selected_id.strip() else None
    shared_ids = {item.id for item in workspaces}
    active_workspace_id = selected_id if selected_id in shared_ids else None
    return WorkspaceListResponse(workspaces=workspaces, active_workspace_id=active_workspace_id)


@router.post("", response_model=WorkspaceCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_workspace(body: WorkspaceCreateRequest, request: Request) -> WorkspaceCreateResponse:
    actor = _session_actor(request)
    if getattr(actor, "system_role", None) != "admin":
        raise HTTPException(status_code=403, detail="Global administrator permission required")

    actor_id = str(actor.id)
    storage_user_id = str(uuid4())
    organization_id = private_organization_id(storage_user_id)
    now = datetime.now(UTC)
    workspace_name = body.name.strip()
    if not workspace_name:
        raise HTTPException(status_code=422, detail="Workspace name must contain a non-whitespace character")

    async with _session_factory()() as session:
        async with session.begin():
            if await session.get(OrganizationRow, organization_id) is not None:
                raise HTTPException(status_code=409, detail="Workspace already exists")
            # The storage principal has no password or OAuth identity and is
            # never issued a session. It exists only so existing owner-scoped
            # persistence and filesystem helpers can share one safe bucket.
            session.add(
                UserRow(
                    id=storage_user_id,
                    email=f"workspace-{storage_user_id}@deerflow.invalid",
                    password_hash=None,
                    system_role="user",
                    created_at=now,
                    oauth_provider=None,
                    oauth_id=None,
                    needs_setup=False,
                    token_version=0,
                )
            )
            session.add(
                OrganizationRow(
                    id=organization_id,
                    slug=private_organization_slug(storage_user_id),
                    name=workspace_name,
                    status="active",
                    storage_user_id=storage_user_id,
                    created_at=now,
                    updated_at=now,
                )
            )
            session.add(
                OrganizationMemberRow(
                    organization_id=organization_id,
                    user_id=actor_id,
                    role="owner",
                    status="active",
                    created_at=now,
                    updated_at=now,
                )
            )

    return WorkspaceCreateResponse(id=organization_id, name=workspace_name, role="owner")


@router.post("/select", response_model=WorkspaceSelectResponse)
async def select_workspace(body: WorkspaceSelectRequest, request: Request, response: Response) -> WorkspaceSelectResponse:
    actor = _session_actor(request)
    actor_id = str(actor.id)
    target_id = body.workspace_id.strip() if isinstance(body.workspace_id, str) else None
    if target_id == "":
        target_id = None

    async with _session_factory()() as session:
        active = await active_organization_for_user(session, actor_id, target_id)
    if active is None:
        raise HTTPException(status_code=404, detail="Workspace not found")

    private_id = private_organization_id(actor_id)
    selected_id = None if active.id == private_id else active.id
    _set_workspace_cookie(response, request, selected_id)
    return WorkspaceSelectResponse(active_workspace_id=selected_id)
