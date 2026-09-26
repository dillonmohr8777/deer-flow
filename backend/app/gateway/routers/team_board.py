"""Momentum team board: staff-only channels, like a small in-product Slack.

Every route runs ``require_momentum_staff`` first (private instance plus a
staff role, else 404). The repository adds the organization boundary, so a
channel in another workspace is indistinguishable from a missing one. The
message author is always the signed-in caller, never a request field.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.gateway.authz import require_permission
from app.gateway.deps import get_config, get_team_board_repo, record_audit_event
from app.gateway.momentum_internal import ADMIN_ROLES, CLIENT_ASSIGNMENT_ROLES, STAFF_ROLES, momentum_staff_only, require_momentum_staff
from deerflow.config.app_config import AppConfig
from deerflow.persistence.clients.model import ClientAssignmentRow
from deerflow.persistence.organizations.model import OrganizationMemberRow
from deerflow.persistence.user.model import UserRow

# Gate first (404 for anyone who isn't Momentum staff), and keep these
# routes out of the public OpenAPI schema.
router = APIRouter(prefix="/api/team", tags=["team"], dependencies=[Depends(momentum_staff_only)], include_in_schema=False)

_SLUG_RE = re.compile(r"[^a-z0-9]+")


class TeamChannelResponse(BaseModel):
    id: str
    slug: str
    name: str
    topic: str
    created_at: str


class TeamChannelListResponse(BaseModel):
    channels: list[TeamChannelResponse]


class TeamChannelCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    topic: str = Field(default="", max_length=255)


class TeamMessageResponse(BaseModel):
    id: str
    channel_id: str
    author_user_id: str
    body: str
    created_at: str


class TeamMessageListResponse(BaseModel):
    messages: list[TeamMessageResponse]


class TeamMessageCreateRequest(BaseModel):
    body: str = Field(..., min_length=1, max_length=4000)


class TeamMemberResponse(BaseModel):
    user_id: str
    email: str
    role: str


class TeamMemberListResponse(BaseModel):
    members: list[TeamMemberResponse]


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Channel not found")


def _slugify(name: str) -> str:
    return _SLUG_RE.sub("-", name.strip().lower()).strip("-")[:64]


def _channel(row: dict) -> TeamChannelResponse:
    return TeamChannelResponse(id=row["id"], slug=row["slug"], name=row["name"], topic=row.get("topic", ""), created_at=row.get("created_at", ""))


def _message(row: dict) -> TeamMessageResponse:
    return TeamMessageResponse(
        id=row["id"],
        channel_id=row["channel_id"],
        author_user_id=row["author_user_id"],
        body=row.get("body", ""),
        created_at=row.get("created_at", ""),
    )


@router.get("/channels", response_model=TeamChannelListResponse)
@require_permission("team", "read")
async def list_team_channels(request: Request, config: AppConfig = Depends(get_config)) -> TeamChannelListResponse:
    """Every channel in the workspace, creating the default set on first use."""
    _, user_id, _ = await require_momentum_staff(request, config)
    rows = await get_team_board_repo(request).ensure_default_channels(created_by_user_id=user_id)
    return TeamChannelListResponse(channels=[_channel(r) for r in rows])


@router.post("/channels", response_model=TeamChannelResponse, status_code=201)
@require_permission("team", "write")
async def create_team_channel(body: TeamChannelCreateRequest, request: Request, config: AppConfig = Depends(get_config)) -> TeamChannelResponse:
    """Owners and admins add channels; members post in the ones that exist."""
    organization_id, user_id, role = await require_momentum_staff(request, config)
    if role not in ADMIN_ROLES:
        await record_audit_event(request, action="team.channel.create", outcome="denied", actor_user_id=user_id, organization_id=organization_id, target_type="team_channel", target_id=None)
        raise HTTPException(status_code=403, detail="Only a workspace owner or admin can add channels")
    slug = _slugify(body.name)
    if not slug:
        raise HTTPException(status_code=422, detail="Channel name needs at least one letter or number")
    row = await get_team_board_repo(request).create_channel(slug=slug, name=body.name.strip(), topic=body.topic.strip(), created_by_user_id=user_id)
    if row is None:
        raise HTTPException(status_code=409, detail=f"A channel named #{slug} already exists")
    await record_audit_event(request, action="team.channel.create", outcome="success", actor_user_id=user_id, organization_id=organization_id, target_type="team_channel", target_id=row["id"])
    return _channel(row)


@router.get("/channels/{channel_id}/messages", response_model=TeamMessageListResponse)
@require_permission("team", "read")
async def list_team_messages(
    channel_id: str,
    request: Request,
    limit: int = Query(default=200, ge=1, le=500),
    config: AppConfig = Depends(get_config),
) -> TeamMessageListResponse:
    await require_momentum_staff(request, config)
    rows = await get_team_board_repo(request).list_messages(channel_id, limit=limit)
    if rows is None:
        raise _not_found()
    return TeamMessageListResponse(messages=[_message(r) for r in rows])


@router.post("/channels/{channel_id}/messages", response_model=TeamMessageResponse, status_code=201)
@require_permission("team", "write")
async def post_team_message(channel_id: str, body: TeamMessageCreateRequest, request: Request, config: AppConfig = Depends(get_config)) -> TeamMessageResponse:
    _, user_id, _ = await require_momentum_staff(request, config)
    text = body.body.strip()
    if not text:
        raise HTTPException(status_code=422, detail="Message is empty")
    row = await get_team_board_repo(request).add_message(channel_id, author_user_id=user_id, body=text)
    if row is None:
        raise _not_found()
    return _message(row)


@router.get("/members", response_model=TeamMemberListResponse)
@require_permission("team", "read")
async def list_team_members(request: Request, config: AppConfig = Depends(get_config)) -> TeamMemberListResponse:
    """Active staff in this workspace, so the board can name message authors.

    Only staff are listed: staff roles, not disabled, and no client_contact
    assignment. A client in the same organization never appears here,
    matching who can read the channels.
    """
    organization_id, _, _ = await require_momentum_staff(request, config)
    # Lazy import so a test's monkeypatched session factory takes effect,
    # matching ``board.py``'s ``_is_active_org_admin``.
    from deerflow.persistence.engine import get_session_factory

    session_factory = get_session_factory()
    if session_factory is None:
        raise HTTPException(status_code=503, detail="Team directory is unavailable")
    stmt = (
        select(UserRow.id, UserRow.email, OrganizationMemberRow.role)
        .join(OrganizationMemberRow, OrganizationMemberRow.user_id == UserRow.id)
        .where(
            OrganizationMemberRow.organization_id == organization_id,
            OrganizationMemberRow.status == "active",
            OrganizationMemberRow.role.in_(sorted(STAFF_ROLES)),
            UserRow.disabled_at.is_(None),
            ~select(ClientAssignmentRow.user_id)
            .where(
                ClientAssignmentRow.organization_id == organization_id,
                ClientAssignmentRow.user_id == UserRow.id,
                ClientAssignmentRow.role.in_(sorted(CLIENT_ASSIGNMENT_ROLES)),
            )
            .exists(),
        )
        .order_by(UserRow.email.asc())
    )
    async with session_factory() as session:
        rows = (await session.execute(stmt)).all()
    return TeamMemberListResponse(members=[TeamMemberResponse(user_id=str(uid), email=email, role=str(role)) for uid, email, role in rows])
