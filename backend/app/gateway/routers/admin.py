"""System-admin controls: user disable/enable/force-logout and the audit log.

Every endpoint here requires ``system_role == "admin"`` (``require_admin_user``,
the same predicate ``managed_models`` and ``mcp`` config routes use) and is
itself audited -- see ``deerflow.persistence.audit_events``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from app.gateway.deps import get_audit_repo, get_current_user_from_request, get_local_provider, record_audit_event, require_admin_user

router = APIRouter(prefix="/api/admin", tags=["admin"])

_ADMIN_REQUIRED_DETAIL = "System administrator privileges are required."


def _network_meta(request: Request) -> dict[str, str | None]:
    return {"ip": request.client.host if request.client else None, "user_agent": request.headers.get("user-agent")}


class AdminUserActionResponse(BaseModel):
    id: str
    email: str
    disabled_at: str | None = None
    token_version: int


async def _load_target_user(user_id: str):
    provider = get_local_provider()
    user = await provider.get_user(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


def _user_action_response(user: Any) -> AdminUserActionResponse:
    return AdminUserActionResponse(
        id=str(user.id),
        email=user.email,
        disabled_at=user.disabled_at.isoformat() if user.disabled_at else None,
        token_version=user.token_version,
    )


@router.post("/users/{user_id}/disable", response_model=AdminUserActionResponse)
async def disable_user(user_id: str, request: Request) -> AdminUserActionResponse:
    """Disable a user: they cannot log in and any live session stops working."""
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)
    actor = await get_current_user_from_request(request)
    user = await _load_target_user(user_id)
    user.disabled_at = datetime.now(UTC)
    user = await get_local_provider().update_user(user)
    await record_audit_event(request, action="admin.user.disabled", outcome="success", actor_user_id=str(actor.id), target_type="user", target_id=user_id, **_network_meta(request))
    return _user_action_response(user)


@router.post("/users/{user_id}/enable", response_model=AdminUserActionResponse)
async def enable_user(user_id: str, request: Request) -> AdminUserActionResponse:
    """Re-enable a previously disabled user."""
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)
    actor = await get_current_user_from_request(request)
    user = await _load_target_user(user_id)
    user.disabled_at = None
    user = await get_local_provider().update_user(user)
    await record_audit_event(request, action="admin.user.enabled", outcome="success", actor_user_id=str(actor.id), target_type="user", target_id=user_id, **_network_meta(request))
    return _user_action_response(user)


@router.post("/users/{user_id}/force-logout", response_model=AdminUserActionResponse)
async def force_logout_user(user_id: str, request: Request) -> AdminUserActionResponse:
    """Invalidate every existing session/JWT for a user by bumping token_version."""
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)
    actor = await get_current_user_from_request(request)
    user = await _load_target_user(user_id)
    user.token_version += 1
    user = await get_local_provider().update_user(user)
    await record_audit_event(request, action="admin.user.force_logout", outcome="success", actor_user_id=str(actor.id), target_type="user", target_id=user_id, **_network_meta(request))
    return _user_action_response(user)


class AuditEventResponse(BaseModel):
    id: str
    occurred_at: str
    actor_user_id: str | None
    organization_id: str | None
    action: str
    target_type: str | None
    target_id: str | None
    outcome: str
    ip: str | None
    user_agent: str | None
    details: dict[str, Any] | None


class AuditEventListResponse(BaseModel):
    events: list[AuditEventResponse]
    next_cursor: str | None = None


@router.get("/audit-events", response_model=AuditEventListResponse)
async def list_audit_events(
    request: Request,
    action_prefix: str | None = Query(default=None, max_length=128),
    actor: str | None = Query(default=None, max_length=64),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    cursor: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=50, ge=1, le=200),
) -> AuditEventListResponse:
    """List audit events across every organization, newest first.

    System-admin scope, not organization scope: the caller manages the whole
    deployment, so this deliberately does not filter by organization (unlike
    the repository's ``organization_id`` parameter, which every org-scoped
    caller elsewhere must pass).
    """
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)
    repo = get_audit_repo(request)
    events, next_cursor = await repo.list(
        organization_id=None,
        action_prefix=action_prefix,
        actor_user_id=actor,
        since=since,
        until=until,
        limit=limit,
        cursor=cursor,
    )
    return AuditEventListResponse(events=[AuditEventResponse(**event) for event in events], next_cursor=next_cursor)


__all__ = ["router"]
