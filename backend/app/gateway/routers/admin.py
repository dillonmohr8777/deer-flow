"""System-admin controls: user disable/enable/force-logout, role changes and the audit log.

Every endpoint here requires ``system_role == "admin"`` (``require_admin_user``,
the same predicate ``managed_models`` and ``mcp`` config routes use) and is
itself audited -- see ``deerflow.persistence.audit_events``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.gateway.auth.models import SystemRole
from app.gateway.authz import role_has_policy
from app.gateway.deps import get_audit_repo, get_current_user_from_request, get_local_provider, record_audit_event, require_admin_user
from app.gateway.no_phi import configured_no_phi_slugs, operator_config
from deerflow.persistence.clients.model import ClientRow
from deerflow.persistence.engine import get_session_factory
from deerflow.persistence.organizations.model import OrganizationRow

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
    if str(actor.id) == user_id:
        raise HTTPException(status_code=400, detail="You can't disable your own account")
    user = await _load_target_user(user_id)
    user.disabled_at = datetime.now(UTC)
    # Also end existing sessions, so re-enabling later doesn't revive them.
    user.token_version += 1
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


class SetUserRoleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    system_role: SystemRole


class AdminUserRoleResponse(BaseModel):
    id: str
    email: str
    system_role: SystemRole


@router.put("/users/{user_id}/role", response_model=AdminUserRoleResponse)
async def set_user_role(user_id: str, body: SetUserRoleRequest, request: Request) -> AdminUserRoleResponse:
    """Set a user's system role (admin, exec, user or client).

    The role is read from the database on every request, so it takes effect
    immediately without ending the user's sessions.
    """
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)
    actor = await get_current_user_from_request(request)
    if str(actor.id) == user_id:
        # Also guarantees the instance never ends up without an admin.
        raise HTTPException(status_code=400, detail="You can't change your own role")
    if not role_has_policy(body.system_role):
        # RBAC fails closed on a role it has no block for: the user would be locked out.
        raise HTTPException(status_code=409, detail=f"Role '{body.system_role}' is not defined under authorization.provider.config.roles; add it before assigning it")
    user = await _load_target_user(user_id)
    previous_role = user.system_role
    user.system_role = body.system_role
    user = await get_local_provider().update_user(user)
    await record_audit_event(
        request,
        action="admin.user.role_changed",
        outcome="success",
        actor_user_id=str(actor.id),
        target_type="user",
        target_id=user_id,
        details={"from": previous_role, "to": user.system_role},
        **_network_meta(request),
    )
    return AdminUserRoleResponse(id=str(user.id), email=user.email, system_role=user.system_role)


class SetNoPhiRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    no_phi: bool


class OrganizationNoPhiResponse(BaseModel):
    id: str
    slug: str
    name: str
    no_phi: bool
    # True when the operator config lists this workspace; the API can't clear that.
    configured: bool
    # What the gateway enforces: the stored flag, the bound client's flag, or the config.
    effective: bool


class ClientNoPhiResponse(BaseModel):
    id: str
    display_name: str
    no_phi: bool


def _require_session_factory():
    factory = get_session_factory()
    if factory is None:
        raise HTTPException(status_code=503, detail="Workspace persistence is unavailable")
    return factory


async def _organization_no_phi_response(session, organization: OrganizationRow) -> OrganizationNoPhiResponse:
    configured = organization.slug.strip().lower() in configured_no_phi_slugs(operator_config())
    client_flag = False
    if organization.customer_client_id:
        client_flag = bool(await session.scalar(select(ClientRow.no_phi).where(ClientRow.id == organization.customer_client_id)))
    return OrganizationNoPhiResponse(
        id=organization.id,
        slug=organization.slug,
        name=organization.name,
        no_phi=bool(organization.no_phi),
        configured=configured,
        effective=bool(organization.no_phi) or configured or client_flag,
    )


@router.get("/organizations/{organization_id}/no-phi", response_model=OrganizationNoPhiResponse)
async def get_organization_no_phi(organization_id: str, request: Request) -> OrganizationNoPhiResponse:
    """Read a workspace's no-PHI flag (health-sector clients). Admin only."""
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)
    async with _require_session_factory()() as session:
        organization = await session.get(OrganizationRow, organization_id)
        if organization is None:
            raise HTTPException(status_code=404, detail="Organization not found")
        return await _organization_no_phi_response(session, organization)


@router.put("/organizations/{organization_id}/no-phi", response_model=OrganizationNoPhiResponse)
async def set_organization_no_phi(organization_id: str, body: SetNoPhiRequest, request: Request) -> OrganizationNoPhiResponse:
    """Flag or unflag a workspace as no-PHI. Only a system admin can; a client never can."""
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)
    actor = await get_current_user_from_request(request)
    async with _require_session_factory()() as session:
        organization = await session.get(OrganizationRow, organization_id)
        if organization is None:
            raise HTTPException(status_code=404, detail="Organization not found")
        previous = bool(organization.no_phi)
        organization.no_phi = body.no_phi
        await session.commit()
        response = await _organization_no_phi_response(session, organization)
    await record_audit_event(
        request,
        action="admin.organization.no_phi_changed",
        outcome="success",
        actor_user_id=str(actor.id),
        organization_id=organization_id,
        target_type="organization",
        target_id=organization_id,
        details={"from": previous, "to": body.no_phi},
        **_network_meta(request),
    )
    return response


@router.put("/clients/{client_id}/no-phi", response_model=ClientNoPhiResponse)
async def set_client_no_phi(client_id: str, body: SetNoPhiRequest, request: Request) -> ClientNoPhiResponse:
    """Flag or unflag a client as no-PHI; every workspace bound to it is then treated as no-PHI. Admin only."""
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)
    actor = await get_current_user_from_request(request)
    async with _require_session_factory()() as session:
        client = await session.get(ClientRow, client_id)
        if client is None:
            raise HTTPException(status_code=404, detail="Client not found")
        previous = bool(client.no_phi)
        client.no_phi = body.no_phi
        await session.commit()
        response = ClientNoPhiResponse(id=client.id, display_name=client.display_name, no_phi=bool(client.no_phi))
    await record_audit_event(
        request,
        action="admin.client.no_phi_changed",
        outcome="success",
        actor_user_id=str(actor.id),
        target_type="client",
        target_id=client_id,
        details={"from": previous, "to": body.no_phi},
        **_network_meta(request),
    )
    return response


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
