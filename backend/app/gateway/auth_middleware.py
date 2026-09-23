"""Global authentication middleware — fail-closed safety net.

Rejects unauthenticated requests to non-public paths with 401. When a
request passes the cookie check, resolves the JWT payload to a real
``User`` object and stamps it into both ``request.state.user`` and the
``deerflow.runtime.user_context`` contextvar so that repository-layer
owner filtering works automatically via the sentinel pattern.

Fine-grained permission checks remain in authz.py decorators.
"""

import logging
from collections.abc import Callable

from fastapi import HTTPException, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

from app.gateway.auth.errors import AuthErrorCode, AuthErrorResponse
from app.gateway.auth_disabled import (
    AUTH_SOURCE_AUTH_DISABLED,
    AUTH_SOURCE_INTERNAL,
    AUTH_SOURCE_PAT,
    AUTH_SOURCE_SESSION,
    get_auth_disabled_user,
    is_auth_disabled,
)
from app.gateway.authz import AuthContext, resolve_route_permissions
from app.gateway.internal_auth import (
    INTERNAL_AUTH_HEADER_NAME,
    INTERNAL_DELEGATION_ID_HEADER_NAME,
    INTERNAL_OWNER_USER_ID_HEADER_NAME,
    get_internal_user,
    is_valid_internal_auth_token,
)
from app.gateway.request_path import get_request_route_path
from deerflow.persistence.organizations.delegation import ActiveDelegation
from deerflow.persistence.organizations.resolution import ActiveOrganization, storage_user_id_for_organization
from deerflow.runtime.user_context import (
    WorkspaceStorageContext,
    reset_current_user,
    reset_storage_context,
    set_current_user,
    set_storage_context,
)

logger = logging.getLogger(__name__)

WORKSPACE_COOKIE_NAME = "deerflow_workspace"
_WORKSPACE_AUTH_EXEMPT_PREFIXES: tuple[str, ...] = (
    "/api/v1/auth/",
    "/api/integrations",
    # Workspace discovery and explicit selection must stay on the actor's
    # private organization so a stale/revoked cookie can be cleared safely.
    "/api/workspaces",
)
# Kept for callers/tests that imported the original single-prefix seam.
_WORKSPACE_AUTH_EXEMPT_PREFIX = "/api/v1/auth/"

# Paths that never require authentication.
_PUBLIC_PATH_PREFIXES: tuple[str, ...] = (
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/api/v1/auth/oauth/",
    "/api/v1/auth/callback/",
    # Inbound webhooks authenticate themselves via provider-specific signatures
    # (e.g. GitHub's X-Hub-Signature-256), not session cookies.
    "/api/webhooks/",
)

# Exact auth paths that are public (login/register/status check).
# /api/v1/auth/me, /api/v1/auth/change-password etc. are NOT public.
_PUBLIC_EXACT_PATHS: frozenset[str] = frozenset(
    {
        "/api/v1/auth/login/local",
        "/api/v1/auth/register",
        "/api/v1/auth/logout",
        "/api/v1/auth/setup-status",
        "/api/v1/auth/initialize",
        "/api/v1/auth/providers",
        # Invitation inspection and acceptance happen before the recipient has
        # a session.  Creation/revocation routes remain protected by the
        # normal middleware and invitation router permissions.
        "/api/v1/auth/invitations/inspect",
        "/api/v1/auth/invitations/accept",
    }
)


def _is_public(path: str) -> bool:
    stripped = path.rstrip("/")
    if stripped in _PUBLIC_EXACT_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in _PUBLIC_PATH_PREFIXES)


async def _resolve_active_workspace(user_id: str, selected_organization_id: str | None) -> ActiveOrganization | None:
    from deerflow.persistence.engine import get_session_factory
    from deerflow.persistence.organizations.resolution import active_organization_for_user

    session_factory = get_session_factory()
    if session_factory is None:
        raise RuntimeError("organization authorization requires a configured database")
    # Keep the existing private-org gate as the compatibility seam used by
    # deployments/tests that override it. A missing private membership is a
    # hard denial; a cookie-selected workspace is resolved independently.
    if selected_organization_id is None:
        private_id = await _resolve_active_private_organization_id(user_id)
        if private_id is None:
            return None
    async with session_factory() as session:
        return await active_organization_for_user(session, user_id, selected_organization_id or private_id)


async def _resolve_active_private_organization_id(user_id: str) -> str | None:
    """Backward-compatible private-org membership resolver."""
    from deerflow.persistence.engine import get_session_factory
    from deerflow.persistence.organizations.resolution import active_private_organization_for_user

    session_factory = get_session_factory()
    if session_factory is None:
        raise RuntimeError("organization authorization requires a configured database")
    async with session_factory() as session:
        return await active_private_organization_for_user(session, user_id)


_DELEGATION_REQUIRED_DETAIL = "Internal calls require an active organization delegation"


async def _resolve_internal_delegation(delegation_id: str | None) -> ActiveDelegation | None:
    """Resolve an internal caller's delegation by id; ``None`` denies."""
    if not delegation_id:
        return None
    from deerflow.persistence.engine import get_session_factory
    from deerflow.persistence.organizations.delegation import OrganizationDelegationRepository

    session_factory = get_session_factory()
    if session_factory is None:
        raise RuntimeError("organization authorization requires a configured database")
    return await OrganizationDelegationRepository(session_factory).resolve_delegation_by_id(delegation_id)


def _workspace_selection_for_request(request: Request, auth_source: str) -> str | None:
    """Return a cookie-selected organization only for browser session calls.

    Credential-management routes and PAT requests always stay on the actor's
    private organization. This prevents an ambient browser cookie from
    widening a bearer-token request or changing account/PAT semantics.
    """
    if auth_source != AUTH_SOURCE_SESSION:
        return None
    if any(get_request_route_path(request).startswith(prefix) for prefix in _WORKSPACE_AUTH_EXEMPT_PREFIXES):
        return None
    selected = request.cookies.get(WORKSPACE_COOKIE_NAME)
    return selected.strip() if selected and selected.strip() else None


class AuthMiddleware(BaseHTTPMiddleware):
    """Strict auth gate: reject requests without a valid session.

    Two-stage check for non-public paths:

    1. Cookie presence — return 401 NOT_AUTHENTICATED if missing
    2. JWT validation via ``get_optional_user_from_request`` — return 401
       TOKEN_INVALID if the token is absent, malformed, expired, or the
       signed user does not exist / is stale

    On success, stamps ``request.state.user`` and the
    ``deerflow.runtime.user_context`` contextvar so that repository-layer
    owner filters work downstream without every route needing a
    ``@require_auth`` decorator. Routes that need per-resource
    authorization (e.g. "user A cannot read user B's thread by guessing
    the URL") should additionally use ``@require_permission(...,
    owner_check=True)`` for explicit enforcement — but authentication
    itself is fully handled here.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if _is_public(get_request_route_path(request)):
            return await call_next(request)

        internal_user = None
        delegation: ActiveDelegation | None = None
        if is_valid_internal_auth_token(request.headers.get(INTERNAL_AUTH_HEADER_NAME)):
            owner_user_id = (request.headers.get(INTERNAL_OWNER_USER_ID_HEADER_NAME) or "").strip() or None
            if is_auth_disabled():
                # Operator override of all authentication (dev/E2E only):
                # keep the legacy synthetic identity.
                internal_user = get_internal_user(owner_user_id=owner_user_id)
            else:
                # Contract section 4: an internal token (plus an owner header)
                # is never enough by itself. The caller names its delegation;
                # it must be active, unexpired, owned by an active member of an
                # active organization, and name the same owner as the header.
                delegation_id = (request.headers.get(INTERNAL_DELEGATION_ID_HEADER_NAME) or "").strip() or None
                try:
                    delegation = await _resolve_internal_delegation(delegation_id)
                except Exception:
                    logger.exception("Could not resolve the delegation of an internal request")
                    return JSONResponse(status_code=503, content={"detail": "Organization authorization is unavailable"})
                if delegation is None or (owner_user_id is not None and owner_user_id != delegation.owner_user_id):
                    logger.warning(
                        "Rejected internal call without a matching active delegation: path=%s delegation_id=%s owner_header=%s",
                        get_request_route_path(request),
                        "present" if delegation_id else "missing",
                        "present" if owner_user_id else "missing",
                    )
                    return JSONResponse(status_code=403, content={"detail": _DELEGATION_REQUIRED_DETAIL})
                internal_user = get_internal_user(owner_user_id=delegation.owner_user_id)

        auth_source = AUTH_SOURCE_SESSION
        access_token = request.cookies.get("access_token")
        authorization = request.headers.get("authorization")
        pat_scopes: frozenset[str] = frozenset()

        # Non-public path: require session cookie
        if internal_user is not None:
            user = internal_user
            auth_source = AUTH_SOURCE_INTERNAL
        elif authorization is not None and not is_auth_disabled():
            # Bearer (PAT) credential precedence (#4849): a present-but-invalid
            # Authorization header is a hard 401 and never silently falls back
            # to the session cookie. This is also what makes the CSRF
            # middleware's Bearer skip safe — a cross-site attacker cannot ride
            # a victim's cookie by padding the request with a garbage Bearer
            # header, because the request dies here before any route runs.
            # Auth-disabled mode is an operator override of all authentication,
            # so it stays ahead of the Bearer check (a stray Authorization
            # header from a proxy must not 401 an E2E sandbox).
            from app.gateway.auth.pat import authenticate_pat, is_pat_allowed_route

            try:
                user, pat_scopes = await authenticate_pat(request.app, authorization)
            except HTTPException as exc:
                return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
            # Default-deny route boundary (#5041 review P1-1): scopes only
            # constrain @require_permission routes, so any route outside the
            # explicit PAT policy is closed to PAT callers outright — an
            # all-scopes token must not reach undecorated mutation routes.
            if not is_pat_allowed_route(request.method, get_request_route_path(request)):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "PAT credentials are not permitted on this route"},
                )
            auth_source = AUTH_SOURCE_PAT
        elif access_token:
            # Strict JWT validation: reject junk/expired tokens with 401
            # right here instead of silently passing through. This closes
            # the "junk cookie bypass" gap (AUTH_TEST_PLAN test 7.5.8):
            # without this, non-isolation routes like /api/models would
            # accept any cookie-shaped string as authentication.
            #
            # We call the *strict* resolver so that fine-grained error
            # codes (token_expired, token_invalid, user_not_found, …)
            # propagate from AuthErrorCode, not get flattened into one
            # generic code. BaseHTTPMiddleware doesn't let HTTPException
            # bubble up, so we catch and render it as JSONResponse here.
            from app.gateway.deps import get_current_user_from_request

            try:
                user = await get_current_user_from_request(request)
            except HTTPException as exc:
                if not is_auth_disabled():
                    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
                user = get_auth_disabled_user()
                auth_source = AUTH_SOURCE_AUTH_DISABLED
        elif is_auth_disabled():
            user = get_auth_disabled_user()
            auth_source = AUTH_SOURCE_AUTH_DISABLED
        else:
            return JSONResponse(
                status_code=401,
                content={
                    "detail": AuthErrorResponse(
                        code=AuthErrorCode.NOT_AUTHENTICATED,
                        message="Authentication required",
                    ).model_dump()
                },
            )

        # Stamp both request.state.user (for the contextvar pattern)
        # and request.state.auth (so @require_permission's "auth is
        # None" branch short-circuits instead of running the entire
        # JWT-decode + DB-lookup pipeline a second time per request).
        request.state.user = user
        request.state.auth_source = auth_source
        organization: ActiveOrganization | None = delegation.organization if delegation is not None else None
        if auth_source in {AUTH_SOURCE_SESSION, AUTH_SOURCE_PAT}:
            try:
                organization = await _resolve_active_workspace(
                    str(user.id),
                    _workspace_selection_for_request(request, auth_source),
                )
            except Exception:
                logger.exception("Could not resolve organization authorization for authenticated request")
                return JSONResponse(status_code=503, content={"detail": "Organization authorization is unavailable"})
            if organization is None:
                return JSONResponse(status_code=403, content={"detail": "Active organization membership required"})
        organization_id = organization.id if organization is not None else None
        # A delegated internal call acts as its owner, never the synthetic user.
        actor_user_id = delegation.owner_user_id if delegation is not None else str(user.id)
        storage_user_id = actor_user_id
        organization_role = None
        if organization is not None:
            storage_user_id = storage_user_id_for_organization(organization, actor_user_id) or ""
            organization_role = organization.role
            if not storage_user_id:
                logger.error("Active organization %s has no valid storage principal", organization.id)
                return JSONResponse(status_code=503, content={"detail": "Organization storage is unavailable"})
        request.state.organization_id = organization_id
        request.state.organization_role = organization_role
        request.state.actor_user_id = actor_user_id
        request.state.storage_user_id = storage_user_id
        request.state.delegation_id = delegation.id if delegation is not None else None
        permissions = await resolve_route_permissions(
            user,
            is_internal=auth_source == AUTH_SOURCE_INTERNAL,
        )
        if auth_source == AUTH_SOURCE_PAT:
            # A PAT can only narrow its owning user's permissions: the stored
            # scopes intersect the resolved route permissions, never widen
            # them, and role changes / authorization policy stay authoritative
            # because they were resolved fresh from the owning user above.
            permissions = [permission for permission in permissions if permission in pat_scopes]
        if delegation is not None:
            # A delegation narrows route permissions exactly like PAT scopes.
            permissions = [permission for permission in permissions if permission in delegation.scopes]
        request.state.auth = AuthContext(
            user=user,
            permissions=permissions,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            storage_user_id=storage_user_id,
            organization_role=organization_role,
        )
        token = set_current_user(user)
        storage_token = set_storage_context(
            WorkspaceStorageContext(
                actor_user_id=actor_user_id,
                organization_id=organization_id,
                storage_user_id=storage_user_id,
                role=organization_role,
            )
        )
        try:
            return await call_next(request)
        finally:
            reset_storage_context(storage_token)
            reset_current_user(token)
