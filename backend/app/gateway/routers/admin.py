"""System-admin controls: user disable/enable/force-logout, role changes, SSO links and the audit log.

Every endpoint here requires ``system_role == "admin"`` (``require_admin_user``,
the same predicate ``managed_models`` and ``mcp`` config routes use) and is
itself audited -- see ``deerflow.persistence.audit_events``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.gateway.auth.models import SystemRole
from app.gateway.authz import role_has_policy
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


# ── SSO identity link ───────────────────────────────────────────────────
#
# A user row holds at most one SSO identity (oauth_provider, oauth_id). These
# routes are the fallback for links the sign-in path refuses to make on its own
# (user_provisioning._link_refusal_reason): the refusal's audit event
# (``auth.oauth.link_refused``) carries the subject to pass here.

_SSO_IDENTITY_TAKEN_DETAIL = "That SSO identity is already linked to another account. Unlink it there first."
_SSO_LINK_CHANGED_DETAIL = "This account's SSO link changed while you were editing it. Reload and try again."


class SetUserOAuthRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1, max_length=32, description="A configured auth.oidc.providers key, e.g. 'google'")
    subject: str = Field(min_length=1, max_length=128, pattern=r"^[\x21-\x7e]+$", description="The provider's stable subject (``sub``) for the person")


class AdminUserOAuthResponse(BaseModel):
    id: str
    email: str
    oauth_provider: str | None
    has_password: bool
    token_version: int


def _configured_oidc_providers() -> set[str]:
    from deerflow.config.app_config import get_app_config

    try:
        return set(get_app_config().auth.oidc.providers)
    except FileNotFoundError:
        return set()


def _oauth_response(user: Any) -> AdminUserOAuthResponse:
    return AdminUserOAuthResponse(
        id=str(user.id),
        email=user.email,
        oauth_provider=user.oauth_provider,
        has_password=user.password_hash is not None,
        token_version=user.token_version,
    )


async def _guard_sso_link_change(user_id: str, request: Request):
    # Imported here: routers.auth is the larger module and imports far more.
    from app.gateway.routers.auth import require_session_source

    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)
    # Linking a sign-in identity is credential management: only an
    # interactive session may do it (the PAT-management / change-password rule).
    require_session_source(request)
    actor = await get_current_user_from_request(request)
    if str(actor.id) == user_id:
        # Unlinking your own SSO-only account would lock you out.
        raise HTTPException(status_code=400, detail="You can't change your own sign-in link")
    return actor


@router.put("/users/{user_id}/oauth", response_model=AdminUserOAuthResponse)
async def link_user_oauth(user_id: str, body: SetUserOAuthRequest, request: Request) -> AdminUserOAuthResponse:
    """Link an SSO identity to a user, replacing any identity they already had.

    Replacing an identity also ends the user's existing sessions, so a session
    from the old identity cannot outlive the change. Only verify the subject
    with the person first: whoever holds it can sign in as this user.
    """
    actor = await _guard_sso_link_change(user_id, request)
    if body.provider not in _configured_oidc_providers():
        raise HTTPException(status_code=400, detail=f"Unknown SSO provider: {body.provider}")
    user = await _load_target_user(user_id)
    provider = get_local_provider()
    holder = await provider.get_user_by_oauth(body.provider, body.subject)
    if holder is not None:
        if str(holder.id) == str(user.id):
            return _oauth_response(user)  # already linked: nothing to change or audit
        raise HTTPException(status_code=409, detail=_SSO_IDENTITY_TAKEN_DETAIL)
    previous_provider, previous_subject = user.oauth_provider, user.oauth_id
    replacing = previous_provider is not None or previous_subject is not None
    try:
        updated = await provider.set_oauth_identity(
            str(user.id),
            body.provider,
            body.subject,
            expected_provider=previous_provider,
            expected_oauth_id=previous_subject,
            revoke_sessions=replacing,
        )
    except ValueError:
        # Lost a race with a sign-in or another admin linking the same identity.
        raise HTTPException(status_code=409, detail=_SSO_IDENTITY_TAKEN_DETAIL) from None
    if updated is None:
        # A sign-in or another admin changed the link (or the user is gone)
        # since it was read; never overwrite what we did not see.
        raise HTTPException(status_code=409, detail=_SSO_LINK_CHANGED_DETAIL)
    user = updated
    await record_audit_event(
        request,
        action="admin.user.oauth_linked",
        outcome="success",
        actor_user_id=str(actor.id),
        target_type="user",
        target_id=str(user.id),
        details={"provider": body.provider, "subject": body.subject, "replaced_provider": previous_provider, "replaced_subject": previous_subject, "sessions_revoked": replacing},
        **_network_meta(request),
    )
    return _oauth_response(user)


@router.delete("/users/{user_id}/oauth", response_model=AdminUserOAuthResponse)
async def unlink_user_oauth(user_id: str, request: Request) -> AdminUserOAuthResponse:
    """Remove a user's SSO identity and end their existing sessions.

    This is for relinking, not for locking someone out: while the provider
    has ``link_existing_accounts`` on, the next verified SSO sign-in for the
    account's email links again. To stop a person signing in, disable the
    account. A user without a password (``has_password: false``) cannot sign
    in until an identity is linked again.
    """
    actor = await _guard_sso_link_change(user_id, request)
    user = await _load_target_user(user_id)
    if user.oauth_provider is None and user.oauth_id is None:
        raise HTTPException(status_code=409, detail="This account has no SSO identity linked")
    previous_provider, previous_subject = user.oauth_provider, user.oauth_id
    updated = await get_local_provider().set_oauth_identity(
        str(user.id),
        None,
        None,
        expected_provider=previous_provider,
        expected_oauth_id=previous_subject,
        revoke_sessions=True,
    )
    if updated is None:
        raise HTTPException(status_code=409, detail=_SSO_LINK_CHANGED_DETAIL)
    user = updated
    await record_audit_event(
        request,
        action="admin.user.oauth_unlinked",
        outcome="success",
        actor_user_id=str(actor.id),
        target_type="user",
        target_id=str(user.id),
        details={"provider": previous_provider, "subject": previous_subject, "sessions_revoked": True},
        **_network_meta(request),
    )
    return _oauth_response(user)


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
