# Placement host boundary: immutable review context

This artifact supplies unchanged host identity, principal resolver, membership, storage context, and CSRF implementations to a changed-file-only reviewer. It contains code and provenance, never an approval. The changed client admission table and real-host HTTP tests are supplied separately by the ordinary packet.

Source commit: `7d46e5a025be91fd7a7db20b06599ccd9337f2fe`. All six modules below are included in full, byte-for-byte. They are unchanged by this PR. This covers the host path reached by a session-authenticated client before the separately supplied placement router performs its explicit organization/user/owner checks. Unknown routes, external send/book actions, and management paths remain outside client admission. The host auth-source and principal resolver suppress internal and PAT authority independently; the extension accepts only session auth.

This does not reproduce all transitive dependencies of the Gateway application. Their imports remain visible; no claim of universal dependency closure is made.

| Source path | Bytes | SHA-256 |
| --- | ---: | --- |
| `backend/app/gateway/auth_middleware.py` | 21186 | `acd84dafe0e091f363d38d4a6c4c5fed0a7fb0f37a5df419621e77d24bda0e40` |
| `backend/app/gateway/csrf_middleware.py` | 12141 | `fa924c198cbe8e3c4dc030a101f99160148a146ab793ed38feb7ae28e5efa6de` |
| `backend/app/gateway/app.py` | 70540 | `cccbfdefd6f72f458823652895de253faa97f9a3db1d206a3891589a968a742b` |
| `backend/packages/extension-api/deerflow_extension_api/auth.py` | 1967 | `5d97e34036d81246b358427193c551c0be974becf4e77507a5243e73e17d5380` |
| `backend/packages/harness/deerflow/persistence/organizations/resolution.py` | 6237 | `985102a553d338c6b05d65576297c0c15c55a7ddd8c608d951e03f3849571288` |
| `backend/packages/harness/deerflow/runtime/user_context.py` | 17769 | `5e028b444ea292160e8543497c7f399d9822ded43c420de8e41d94acedc5db72` |

## backend/app/gateway/auth_middleware.py

````python
"""Global authentication middleware — fail-closed safety net.

Rejects unauthenticated requests to non-public paths with 401. When a
request passes the cookie check, resolves the JWT payload to a real
``User`` object and stamps it into both ``request.state.user`` and the
``deerflow.runtime.user_context`` contextvar so that repository-layer
owner filtering works automatically via the sentinel pattern.

Fine-grained permission checks remain in authz.py decorators.
"""

import logging
import re
from collections.abc import Callable

from fastapi import HTTPException, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

from app.gateway.auth.errors import AuthErrorCode, AuthErrorResponse
from app.gateway.auth.session_cookie import ACCESS_TOKEN_COOKIE_NAME
from app.gateway.auth_disabled import (
    AUTH_SOURCE_AUTH_DISABLED,
    AUTH_SOURCE_INTERNAL,
    AUTH_SOURCE_PAT,
    AUTH_SOURCE_SESSION,
    get_auth_disabled_user,
    is_auth_disabled,
)
from app.gateway.authz import AuthContext, resolve_route_permissions
from app.gateway.client_boundary import CLIENT_ROLE, is_client_allowed_route
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

# Personal access tokens are themselves an organization-scoped resource (M3,
# migration 0037_pat_organization): unlike genuine credential-management
# routes (login, password change, MFA, invitations -- which must stay pinned
# to the actor's identity regardless of any cookie), PAT create/list/revoke
# is carved out of the blanket ``/api/v1/auth/`` exemption above so the
# session's active organization (the workspace-selection cookie) selects
# which organization a PAT is minted for, listed from, or revoked in -- the
# same ``organization_for_write`` treatment every other M3 resource gets.
# This is safe precisely because organization selection is fail-closed
# (``active_organization_for_user`` re-verifies active membership before any
# row is stamped or returned): a stale/forged cookie naming an organization
# the caller cannot prove membership in 403s the whole request rather than
# widening it.
_PAT_MANAGEMENT_PREFIX = "/api/v1/auth/pats"

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
        # The caller holds only the single-use challenge from login/local's
        # mfa_required response, not a session yet -- the challenge itself
        # (signed, short-lived, attempt-limited) is the auth boundary here.
        "/api/v1/auth/login/mfa",
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

    Credential-management routes always stay on the actor's private
    organization, preventing an ambient browser cookie from widening a
    bearer-token request or changing account semantics. PAT management
    (``/api/v1/auth/pats``) is carved out of that exemption: a PAT is itself
    an organization-scoped resource, so its active organization is selected
    the same way every other M3 resource's is (see ``_PAT_MANAGEMENT_PREFIX``).
    """
    if auth_source != AUTH_SOURCE_SESSION:
        return None
    path = get_request_route_path(request)
    composio_path = path in {"/api/integrations/connect", "/api/integrations/callback", "/api/integrations/status"} or re.fullmatch(r"/api/integrations/connect/[A-Za-z0-9_-]{24}/open", path) is not None
    if not path.startswith(_PAT_MANAGEMENT_PREFIX) and not composio_path and any(path.startswith(prefix) for prefix in _WORKSPACE_AUTH_EXEMPT_PREFIXES):
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
        access_token = request.cookies.get(ACCESS_TOKEN_COOKIE_NAME)
        authorization = request.headers.get("authorization")
        pat_scopes: frozenset[str] = frozenset()
        pat_organization_id: str | None = None

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
            from deerflow.config.app_config import get_app_config

            try:
                user, pat_scopes, pat_organization_id = await authenticate_pat(request.app, authorization)
            except HTTPException as exc:
                return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
            # Default-deny route boundary (#5041 review P1-1): scopes only
            # constrain @require_permission routes, so any route outside the
            # explicit PAT policy is closed to PAT callers outright — an
            # all-scopes token must not reach undecorated mutation routes.
            # private_workspace.enabled additionally gates the fleet/agents/
            # scheduled-task routes (PR #14 review): false on every
            # client-facing MomoBot, so a leaked client PAT cannot create a
            # persistent custom agent or schedule it to run unattended. Fails
            # closed (disabled) on any config-resolution error -- a missing
            # or malformed config.yaml must never crash authenticated
            # requests, and "closed" here means the strictest, safest policy
            # anyway.
            try:
                private_workspace_enabled = get_app_config().private_workspace.enabled
            except Exception:
                private_workspace_enabled = False
            if not is_pat_allowed_route(request.method, get_request_route_path(request), private_workspace_enabled=private_workspace_enabled):
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
        # A client (external customer) reaches chat and nothing else; the table
        # is default-deny, so it also closes routes added after it was written.
        if getattr(user, "system_role", None) == CLIENT_ROLE and not is_client_allowed_route(request.method, get_request_route_path(request)):
            return JSONResponse(status_code=403, content={"detail": "This area is not available for your account"})
        organization: ActiveOrganization | None = delegation.organization if delegation is not None else None
        if auth_source in {AUTH_SOURCE_SESSION, AUTH_SOURCE_PAT}:
            # A PAT is pinned to the organization active when it was minted
            # (its own stamped ``organization_id``, migration
            # 0037_pat_organization) — never to a workspace-selection cookie,
            # which only ever applies to interactive sessions. This is what
            # stops a PAT minted in one organization from acting in another
            # even if the bearer request carries a stale/forged workspace
            # cookie, and what makes a since-revoked membership in that
            # organization fail closed below (organization is None -> 403).
            selected_organization_id = pat_organization_id if auth_source == AUTH_SOURCE_PAT else _workspace_selection_for_request(request, auth_source)
            try:
                organization = await _resolve_active_workspace(
                    str(user.id),
                    selected_organization_id,
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
````

## backend/app/gateway/csrf_middleware.py

````python
"""CSRF protection middleware for FastAPI.

Per RFC-001:
State-changing operations require CSRF protection.
"""

import os
import secrets
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

from app.gateway.auth.config import get_auth_config
from app.gateway.auth.session_cookie_state import SESSION_COOKIE_ISSUED_STATE_ATTR, SESSION_COOKIE_MAX_AGE_STATE_ATTR, SESSION_COOKIE_SECURE_STATE_ATTR, SKIP_AUTH_CSRF_COOKIE_STATE_ATTR
from app.gateway.auth_disabled import is_auth_disabled
from app.gateway.request_path import get_request_route_path
from deerflow.trace_context import TRACE_ID_HEADER

CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"
CSRF_TOKEN_LENGTH = 64  # bytes
_CSRF_STATE_CHANGING_METHODS: frozenset[str] = frozenset({"POST", "PUT", "DELETE", "PATCH"})
_CSRF_EXEMPT_EXACT_PATHS: frozenset[str] = frozenset({"/api/v1/auth/me"})


def is_secure_request(request: Request) -> bool:
    """Detect whether the original client request was made over HTTPS."""
    return _request_scheme(request) == "https"


def generate_csrf_token() -> str:
    """Generate a secure random CSRF token."""
    return secrets.token_urlsafe(CSRF_TOKEN_LENGTH)


def should_check_csrf(request: Request) -> bool:
    """Determine if a request needs CSRF validation.

    CSRF is checked for state-changing methods (POST, PUT, DELETE, PATCH).
    GET, HEAD, OPTIONS, and TRACE are exempt per RFC 7231.
    """
    if request.method not in _CSRF_STATE_CHANGING_METHODS:
        return False

    if is_auth_disabled():
        return False

    route_path = get_request_route_path(request)
    path = route_path.rstrip("/")
    # Exempt host-owned endpoints that implement their own request posture.
    if path in _CSRF_EXEMPT_EXACT_PATHS:
        return False
    # Inbound webhooks authenticate themselves via provider-specific signatures
    # (e.g. GitHub's X-Hub-Signature-256), not the CSRF double-submit cookie.
    if route_path.startswith("/api/webhooks/"):
        return False
    return True


_AUTH_EXEMPT_PATHS: frozenset[str] = frozenset(
    {
        "/api/v1/auth/login/local",
        "/api/v1/auth/login/mfa",
        "/api/v1/auth/logout",
        "/api/v1/auth/register",
        "/api/v1/auth/initialize",
        "/api/v1/auth/invitations/inspect",
        # Exempt here because a brand-new recipient has no session (so no
        # csrf_token cookie) yet. When accept acts on an existing account's
        # session instead, the handler enforces the double-submit pair itself
        # (routers/invitations.py::_csrf_double_submit_matches).
        "/api/v1/auth/invitations/accept",
    }
)


def is_auth_endpoint(request: Request) -> bool:
    """Check if the request is to an auth endpoint.

    Auth endpoints don't need CSRF validation on first call (no token).
    """
    return get_request_route_path(request).rstrip("/") in _AUTH_EXEMPT_PATHS


def _host_with_optional_port(hostname: str, port: int | None, scheme: str) -> str:
    """Return normalized host[:port], omitting default ports."""
    host = hostname.lower()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"

    if port is None or (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        return host
    return f"{host}:{port}"


def _normalize_origin(origin: str) -> str | None:
    """Return a normalized scheme://host[:port] origin, or None for invalid input."""
    try:
        parsed = urlsplit(origin.strip())
        port = parsed.port
    except ValueError:
        return None

    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not parsed.hostname:
        return None

    # Browser Origin is only scheme/host/port. Reject URL-shaped or credentialed values.
    if parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
        return None

    return f"{scheme}://{_host_with_optional_port(parsed.hostname, port, scheme)}"


def _configured_cors_origins() -> set[str]:
    """Return explicit configured browser origins that may call auth routes."""
    origins = set()
    for raw_origin in os.environ.get("GATEWAY_CORS_ORIGINS", "").split(","):
        origin = raw_origin.strip()
        if not origin or origin == "*":
            continue
        normalized = _normalize_origin(origin)
        if normalized:
            origins.add(normalized)
    return origins


def get_configured_cors_origins() -> set[str]:
    """Return normalized explicit browser origins from GATEWAY_CORS_ORIGINS."""
    return _configured_cors_origins()


# Response headers a split-origin browser client must be able to read. Only the
# CORS-safelisted set is visible to JS by default, and the created run's id
# travels in `Content-Location` — the LangGraph SDK resolves run metadata from
# it, so withholding it leaves such a client unable to learn its own run id.
# `X-Trace-Id` is listed for the same reason: TraceMiddleware puts it on every
# response as the correlation id to quote in a bug report, and unexposed it is
# readable on same-origin nginx deployments but invisible to exactly the
# split-origin clients that cannot see the Gateway's logs either.
CORS_EXPOSED_HEADERS: tuple[str, ...] = ("Content-Location", TRACE_ID_HEADER)


def _first_header_value(value: str | None) -> str | None:
    """Return the first value from a comma-separated proxy header."""
    if not value:
        return None
    first = value.split(",", 1)[0].strip()
    return first or None


def _forwarded_param(request: Request, name: str) -> str | None:
    """Extract a parameter from the first RFC 7239 Forwarded header entry."""
    forwarded = _first_header_value(request.headers.get("forwarded"))
    if not forwarded:
        return None

    for part in forwarded.split(";"):
        key, sep, value = part.strip().partition("=")
        if sep and key.lower() == name:
            return value.strip().strip('"') or None
    return None


def _request_scheme(request: Request) -> str:
    """Resolve the original request scheme from trusted proxy headers."""
    scheme = _forwarded_param(request, "proto") or _first_header_value(request.headers.get("x-forwarded-proto")) or request.url.scheme
    return scheme.lower()


def _request_origin(request: Request) -> str | None:
    """Build the origin for the URL the browser is targeting."""
    scheme = _request_scheme(request)
    host = _forwarded_param(request, "host") or _first_header_value(request.headers.get("x-forwarded-host")) or request.headers.get("host") or request.url.netloc

    forwarded_port = _first_header_value(request.headers.get("x-forwarded-port"))
    if forwarded_port and ":" not in host.rsplit("]", 1)[-1]:
        host = f"{host}:{forwarded_port}"

    return _normalize_origin(f"{scheme}://{host}")


def is_allowed_auth_origin(request: Request) -> bool:
    """Allow auth POSTs only from the same origin or explicit configured origins.

    Login/register/initialize are exempt from the double-submit token because
    first-time browser clients do not have a CSRF token yet. They still create
    a session cookie, so browser requests with a hostile Origin header must be
    rejected to prevent login CSRF / session fixation. Requests without Origin
    are allowed for non-browser clients such as curl and mobile integrations.
    """
    origin = request.headers.get("origin")
    if not origin:
        return True

    normalized_origin = _normalize_origin(origin)
    if normalized_origin is None:
        return False

    request_origin = _request_origin(request)
    return normalized_origin in _configured_cors_origins() or (request_origin is not None and normalized_origin == request_origin)


def auth_csrf_cookie_settings(request: Request) -> tuple[bool, int | None]:
    """Return ``(secure, max_age)`` for auth-created CSRF cookies."""
    session_cookie_issued = getattr(request.state, SESSION_COOKIE_ISSUED_STATE_ATTR, False)
    if session_cookie_issued:
        return (
            bool(getattr(request.state, SESSION_COOKIE_SECURE_STATE_ATTR, is_secure_request(request))),
            getattr(request.state, SESSION_COOKIE_MAX_AGE_STATE_ATTR, None),
        )

    secure = is_secure_request(request)
    max_age = get_auth_config().token_expiry_days * 24 * 3600 if secure else None
    return secure, max_age


class CSRFMiddleware(BaseHTTPMiddleware):
    """Middleware that implements CSRF protection using Double Submit Cookie pattern."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        _is_auth = is_auth_endpoint(request)

        if should_check_csrf(request) and _is_auth and not is_allowed_auth_origin(request):
            return JSONResponse(
                status_code=403,
                content={"detail": "Cross-site auth request denied."},
            )

        if should_check_csrf(request) and not _is_auth and request.headers.get("authorization") is None:
            # Bearer-authenticated requests (PAT, #4849) are exempt from the
            # cookie double-submit check only — the cross-site origin check on
            # auth endpoints above still runs for every request. Safety rests
            # on AuthMiddleware's strict Bearer precedence: an invalid Bearer
            # header is a 401 there, so a cross-site attacker cannot ride a
            # victim's cookie by padding a garbage Authorization header, and a
            # cross-site request carrying a custom Authorization header at all
            # requires a CORS preflight the attacker cannot obtain.
            cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
            header_token = request.headers.get(CSRF_HEADER_NAME)

            if not cookie_token or not header_token:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "CSRF token missing. Include X-CSRF-Token header."},
                )

            if not secrets.compare_digest(cookie_token, header_token):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "CSRF token mismatch."},
                )

        response = await call_next(request)

        # For auth endpoints that set up session, also set CSRF cookie.
        # Session-creating handlers may stamp the final access-token max_age on
        # request.state; mirroring it here keeps the double-submit cookie pair
        # from diverging across HTTPS, localhost, and sandbox deployments.
        if _is_auth and request.method == "POST" and not getattr(request.state, SKIP_AUTH_CSRF_COOKIE_STATE_ATTR, False):
            # Generate a new CSRF token for the session
            csrf_token = generate_csrf_token()
            secure, max_age = auth_csrf_cookie_settings(request)
            response.set_cookie(
                key=CSRF_COOKIE_NAME,
                value=csrf_token,
                httponly=False,  # Must be JS-readable for Double Submit Cookie pattern
                secure=secure,
                samesite="strict",
                # Match the access_token cookie's lifetime (auth.py::_set_session_cookie)
                # so the double-submit pair never diverges. A session-only csrf_token is
                # evicted when iOS Safari terminates a home-screen PWA while the persistent
                # access_token survives — leaving the user "logged in" but unable to make
                # any state-changing request (403 "CSRF token missing").
                max_age=max_age,
            )

        return response


def get_csrf_token(request: Request) -> str | None:
    """Get the CSRF token from the current request's cookies.

    This is useful for server-side rendering where you need to embed
    token in forms or headers.
    """
    return request.cookies.get(CSRF_COOKIE_NAME)
````

## backend/app/gateway/app.py

````python
import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress

from deerflow_extension_api import EXTENSION_PRINCIPAL_RESOLVER_KEY, ExtensionPrincipal
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.gateway.auth_disabled import AUTH_SOURCE_INTERNAL, AUTH_SOURCE_PAT, warn_if_auth_disabled_enabled
from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.browser_capability import ensure_browser_runtime_available
from app.gateway.config import get_gateway_config
from app.gateway.csrf_middleware import CORS_EXPOSED_HEADERS, CSRFMiddleware, get_configured_cors_origins
from app.gateway.deps import langgraph_runtime
from app.gateway.health import READINESS_CHECKPOINTER_CONFIG_ATTR, readiness_payload
from app.gateway.routers import (
    academy,
    admin,
    agent_room,
    agents,
    approvals,
    artifacts,
    assistants_compat,
    auth,
    board,
    browser,
    browserbase_research,
    capabilities,
    channel_connections,
    channels,
    client_portal,
    clients,
    command_center,
    composio_connect,
    console,
    cost_router,
    features,
    feedback,
    fleet,
    fleet_work,
    github_webhooks,
    input_polish,
    integrations,
    invitations,
    knowledge,
    mcp,
    mcp_tasks,
    memory,
    models,
    momobot_brand,
    onboarding,
    openai_agents,
    plugins,
    project_documents,
    project_thread_files,
    projects,
    runs,
    scheduled_tasks,
    skills,
    subagent_batches,
    subagents,
    suggestions,
    team_board,
    thread_runs,
    threads,
    trash,
    uploads,
    user_preferences,
    workflows,
    workspace_branding,
    workspaces,
    wsl_diagnostics,
)
from app.gateway.trace_middleware import TraceMiddleware
from deerflow.config import app_config as deerflow_app_config
from deerflow.logging_config import DEFAULT_LOG_DATE_FORMAT, DEFAULT_LOG_FORMAT, configure_logging
from deerflow.tracing.monocle import setup_monocle_tracing_if_enabled
from deerflow.uploads.manager import cleanup_stale_upload_staging_files
from deerflow.utils.file_io import await_drained

AppConfig = deerflow_app_config.AppConfig
get_app_config = deerflow_app_config.get_app_config

# Default logging; lifespan overrides from config.yaml log_level.
logging.basicConfig(
    level=logging.INFO,
    format=DEFAULT_LOG_FORMAT,
    datefmt=DEFAULT_LOG_DATE_FORMAT,
)

logger = logging.getLogger(__name__)

# Grace budget (seconds) lifespan shutdown hooks get for ordinary completion.
# Hooks that own uncancellable executor work may spend additional time draining
# already-started work after cancellation rather than detach it from teardown.
_SHUTDOWN_HOOK_TIMEOUT_SECONDS = 5.0

# The retrieval index is derived state, so shutdown only waits briefly for its
# startup rebuild. The canonical memory flush keeps its full configured budget.
_RETRIEVAL_WARM_SHUTDOWN_TIMEOUT_SECONDS = 1.0


async def _ensure_admin_user(app: FastAPI) -> None:
    """Startup hook: handle first boot and migrate orphan threads otherwise.

    After admin creation, migrate orphan threads from the LangGraph
    store (metadata.user_id unset) to the admin account. This is the
    "no-auth → with-auth" upgrade path: users who ran DeerFlow without
    authentication have existing LangGraph thread data that needs an
    owner assigned.
        First boot (no admin exists):
            - Does NOT create any user accounts automatically.
            - The operator must visit ``/setup`` to create the first admin.

    Subsequent boots (admin already exists):
      - Runs the one-time "no-auth → with-auth" orphan thread migration for
        existing LangGraph thread metadata that has no user_id.

    No SQL persistence migration is needed: the four user_id columns
    (threads_meta, runs, run_events, feedback) only come into existence
    alongside the auth module via create_all, so freshly created tables
    never contain NULL-owner rows.
    """
    from sqlalchemy import select

    from app.gateway.deps import get_local_provider
    from deerflow.persistence.engine import get_session_factory
    from deerflow.persistence.user.model import UserRow

    try:
        provider = get_local_provider()
    except RuntimeError:
        # Auth persistence may not be initialized in some test/boot paths.
        # Skip admin migration work rather than failing gateway startup.
        logger.warning("Auth persistence not ready; skipping admin bootstrap check")
        return

    sf = get_session_factory()
    if sf is None:
        return

    admin_count = await provider.count_admin_users()

    if admin_count == 0:
        logger.info("=" * 60)
        logger.info("  First boot detected — no admin account exists.")
        logger.info("  Visit /setup to complete admin account creation.")
        logger.info("=" * 60)
        return

    # Admin already exists — run orphan thread migration for any
    # LangGraph thread metadata that pre-dates the auth module.
    async with sf() as session:
        stmt = select(UserRow).where(UserRow.system_role == "admin").limit(1)
        row = (await session.execute(stmt)).scalar_one_or_none()

    if row is None:
        return  # Should not happen (admin_count > 0 above), but be safe.

    admin_id = str(row.id)

    # LangGraph store orphan migration — non-fatal.
    # This covers the "no-auth → with-auth" upgrade path for users
    # whose existing LangGraph thread metadata has no user_id set.
    store = getattr(app.state, "store", None)
    if store is not None:
        try:
            migrated = await _migrate_orphaned_threads(store, admin_id)
            if migrated:
                logger.info("Migrated %d orphan LangGraph thread(s) to admin", migrated)
        except Exception:
            logger.exception("LangGraph thread migration failed (non-fatal)")


async def _iter_store_items(store, namespace, *, page_size: int = 500):
    """Paginated async iterator over a LangGraph store namespace.

    Replaces the old hardcoded ``limit=1000`` call with a cursor-style
    loop so that environments with more than one page of orphans do
    not silently lose data. Terminates when a page is empty OR when a
    short page arrives (indicating the last page).
    """
    offset = 0
    while True:
        batch = await store.asearch(namespace, limit=page_size, offset=offset)
        if not batch:
            return
        for item in batch:
            yield item
        if len(batch) < page_size:
            return
        offset += page_size


async def _migrate_orphaned_threads(store, admin_user_id: str) -> int:
    """Migrate LangGraph store threads with no user_id to the given admin.

    Uses cursor pagination so all orphans are migrated regardless of
    count. Returns the number of rows migrated.
    """
    migrated = 0
    async for item in _iter_store_items(store, ("threads",)):
        metadata = item.value.get("metadata", {})
        if not metadata.get("user_id"):
            metadata["user_id"] = admin_user_id
            item.value["metadata"] = metadata
            await store.aput(("threads",), item.key, item.value)
            migrated += 1
    return migrated


async def _warm_memory_retrieval(manager) -> None:
    """Rebuild the derived retrieval index without delaying Gateway readiness."""
    try:
        rebuilt = await asyncio.to_thread(manager.warm_retrieval)
        if rebuilt:
            logger.info("Memory retrieval index rebuilt successfully")
        else:
            logger.warning("Memory retrieval index rebuild failed; scoped searches will retry lazily")
    except Exception:
        logger.warning("Memory retrieval index rebuild skipped", exc_info=True)


async def _shutdown_memory_backend(*, retrieval_warm_finished: bool) -> None:
    """Resolve, drain, and close memory within the caller's cancellation shield.

    Backend ``close()`` overrides must be quick or internally bounded: unlike
    ``shutdown_flush``, close has no host timeout and is drained even on cancellation.
    """
    manager = None
    try:
        app_cfg: AppConfig = await asyncio.to_thread(get_app_config)
        if app_cfg.memory.enabled:
            from deerflow.agents.memory import get_memory_manager

            manager = await asyncio.to_thread(get_memory_manager)
            flush_timeout = app_cfg.memory.shutdown_flush_timeout_seconds
            completed = await asyncio.to_thread(manager.shutdown_flush, flush_timeout)
            if completed:
                logger.info("Memory queue flush completed within %.1fs", flush_timeout)
            else:
                logger.warning(
                    "Memory queue flush did not finish within %.1fs; remaining updates may be lost",
                    flush_timeout,
                )
    except Exception:
        logger.exception("Failed to flush memory queue on shutdown")
    finally:
        close = getattr(manager, "close", None)
        if callable(close) and retrieval_warm_finished:
            try:
                await asyncio.to_thread(close)
            except Exception:
                logger.exception("Failed to close memory backend on shutdown")


async def _run_startup_trash_sweep(app: FastAPI, startup_config) -> None:
    """One trash retention sweep at gateway startup (Phase-2 spec §8.3).

    Runs beside the lazy trigger on the trash listing — no daemon, no
    scheduler (§15.9). Sweeps every user (``user_id=None``) with the
    configured retention window, including the full reconciliation. A sweep
    failure is logged and never blocks gateway readiness; on shutdown the
    lifespan gives it a bounded graceful-completion budget, then cancels an
    overrun while draining any already-started file reconciliation before
    teardown continues.
    """
    try:
        from deerflow.config.paths import get_paths
        from deerflow.config.projects_config import ProjectsConfig
        from deerflow.projects.trash import run_trash_retention_sweep

        project_document_repo = getattr(app.state, "project_document_repo", None)
        if project_document_repo is None:
            return
        projects_config = getattr(startup_config, "projects", None)
        retention_days = projects_config.trash_retention_days if projects_config is not None else ProjectsConfig().trash_retention_days
        sweep_report = await run_trash_retention_sweep(project_document_repo, get_paths(), retention_days=retention_days, user_id=None)
        if sweep_report.purged or sweep_report.orphans_removed or sweep_report.staging_removed or sweep_report.content_missing:
            logger.info(
                "Trash retention sweep: purged=%d failures=%d orphans=%d staging=%d content_missing=%d",
                sweep_report.purged,
                sweep_report.purge_failures,
                sweep_report.orphans_removed,
                sweep_report.staging_removed,
                len(sweep_report.content_missing),
            )
    except Exception:
        logger.warning("Trash retention sweep skipped", exc_info=True)


async def _shutdown_startup_trash_sweep(app: FastAPI) -> None:
    """Grace-budgeted shutdown for the background startup sweep (§8.3).

    Waits ``_SHUTDOWN_HOOK_TIMEOUT_SECONDS`` for graceful completion, then
    cancels an overrun. That budget is not a hard upper bound for this hook:
    reconciliation runs in executor threads that cannot be safely killed, so
    cancellation drains any already-started filesystem worker before returning.
    This keeps the sweep's file ownership intact until the teardown below can
    safely dispose the document repo and DB engine.
    """
    task = getattr(app.state, "startup_trash_sweep_task", None)
    if task is None or task.done():
        return
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=_SHUTDOWN_HOOK_TIMEOUT_SECONDS)
    except TimeoutError:
        # Cancellation prevents later sweep stages from starting, but an
        # executor-backed reconciliation that already started drains before
        # ``CancelledError`` reaches this task. The final await may therefore
        # exceed the graceful-completion budget; detaching that worker would
        # reintroduce teardown/file-mutation overlap. A ``cancel()`` that
        # returns False means the sweep finished inside the window between the
        # deadline firing and this call — report that as the late finish it is.
        cancelled = task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        if cancelled:
            logger.warning(
                "Startup trash sweep exceeded %.1fs during shutdown; cancelled and drained before proceeding with worker exit.",
                _SHUTDOWN_HOOK_TIMEOUT_SECONDS,
            )
        else:
            logger.info(
                "Startup trash sweep finished just after the %.1fs shutdown budget; proceeding with worker exit.",
                _SHUTDOWN_HOOK_TIMEOUT_SECONDS,
            )
    except Exception:
        logger.exception("Startup trash sweep failed during shutdown")


async def _announce_to_exec_without_receipt(text: str) -> None:
    """Adapt the confirmed-post API for fire-and-forget sweep callbacks.

    Scorecard evaluation retains the original boolean receipt contract.
    """
    from deerflow.tools.exec_seat_tools import announce_to_exec

    await announce_to_exec(text)


async def _run_seat_budget_sweep() -> None:
    """One weekly-budget pause/resume pass over every organization's agent seats (queue item f95).

    ``deerflow.exec_seats.budget.evaluate_seat_budget`` and its ``#exec``
    announcement are organization-scoped (``AgentSeatRepository``'s ambient
    ``resolve_organization_id()``, ``TeamBoardRepository``'s the same), so
    each organization's seats are evaluated inside that organization's own
    storage context -- otherwise the announcement would resolve no channel
    (or the wrong one) and ``AgentSeatRepository.set_paused`` would refuse
    every write as foreign.
    """
    from sqlalchemy import select

    from deerflow.exec_seats.budget import evaluate_seat_budget
    from deerflow.persistence.engine import get_session_factory
    from deerflow.persistence.exec_seats import AgentSeatRepository
    from deerflow.persistence.organizations.model import OrganizationMemberRow, OrganizationRow
    from deerflow.runtime.user_context import WorkspaceStorageContext, reset_storage_context, set_storage_context

    session_factory = get_session_factory()
    if session_factory is None:
        return
    repo = AgentSeatRepository(session_factory)
    seats_by_org: dict[str, list[dict]] = {}
    for seat in await repo.list_seats():
        seats_by_org.setdefault(seat["organization_id"], []).append(seat)

    for organization_id, org_seats in seats_by_org.items():
        async with session_factory() as session:
            storage_user_id = await session.scalar(select(OrganizationRow.storage_user_id).where(OrganizationRow.id == organization_id))
            owner_user_id = await session.scalar(
                select(OrganizationMemberRow.user_id).where(
                    OrganizationMemberRow.organization_id == organization_id,
                    OrganizationMemberRow.role == "owner",
                    OrganizationMemberRow.status == "active",
                )
            )
        if owner_user_id is None:
            # No active owner to attribute the sweep to (org mid-deletion,
            # data oddity): still safe to skip -- pause/resume is not urgent
            # enough to guess an identity for.
            continue
        token = set_storage_context(WorkspaceStorageContext(actor_user_id=owner_user_id, organization_id=organization_id, storage_user_id=storage_user_id or owner_user_id))
        try:
            for seat in org_seats:
                await evaluate_seat_budget(repo, seat, announce=_announce_to_exec_without_receipt)
        finally:
            reset_storage_context(token)


async def _run_seat_budget_loop(interval_seconds: float) -> None:
    """Recurring seat-budget sweep, cancelled cleanly on shutdown (queue item f95)."""
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            await _run_seat_budget_sweep()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Seat budget sweep failed")


def _start_seat_budget_loop(startup_config) -> asyncio.Task | None:
    """Schedule the recurring sweep when configured; ``None`` otherwise.

    Defensive against unconfigured ``startup_config`` test doubles (a bare
    ``SimpleNamespace``/``MagicMock`` with no ``exec_seats`` attribute) the
    same way the scheduler and trash-sweep gates already are: only a real
    ``ExecSeatsConfig`` with ``budget_check_enabled=True`` starts the loop.
    """
    from deerflow.config.exec_seats_config import ExecSeatsConfig

    exec_seats_config = getattr(startup_config, "exec_seats", None)
    if not isinstance(exec_seats_config, ExecSeatsConfig) or not exec_seats_config.budget_check_enabled:
        return None
    return asyncio.create_task(_run_seat_budget_loop(exec_seats_config.budget_check_interval_seconds))


async def _shutdown_seat_budget_loop(app: FastAPI) -> None:
    """Cancel the recurring sweep task, if one was started."""
    task = getattr(app.state, "seat_budget_loop_task", None)
    if task is None or task.done():
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


async def _run_seat_scorecard_sweep() -> None:
    """One weekly-scorecard pass over every organization's agent seats (queue item e11).

    Same per-organization storage-context shape as ``_run_seat_budget_sweep``
    (``deerflow.exec_seats.scorecard.evaluate_seat_scorecard`` and its
    ``#exec`` announcement are organization-scoped via ambient
    ``resolve_organization_id()``), and the same "skip an org with no active
    owner to attribute the sweep to" posture.
    """
    from sqlalchemy import select

    from deerflow.exec_seats.scorecard import evaluate_seat_scorecard
    from deerflow.persistence.engine import get_session_factory
    from deerflow.persistence.exec_seats import AgentSeatRepository
    from deerflow.persistence.organizations.model import OrganizationMemberRow, OrganizationRow
    from deerflow.runtime.user_context import WorkspaceStorageContext, reset_storage_context, set_storage_context
    from deerflow.tools.exec_seat_tools import announce_to_exec

    session_factory = get_session_factory()
    if session_factory is None:
        return
    repo = AgentSeatRepository(session_factory)
    seats_by_org: dict[str, list[dict]] = {}
    for seat in await repo.list_seats():
        seats_by_org.setdefault(seat["organization_id"], []).append(seat)

    for organization_id, org_seats in seats_by_org.items():
        async with session_factory() as session:
            storage_user_id = await session.scalar(select(OrganizationRow.storage_user_id).where(OrganizationRow.id == organization_id))
            owner_user_id = await session.scalar(
                select(OrganizationMemberRow.user_id).where(
                    OrganizationMemberRow.organization_id == organization_id,
                    OrganizationMemberRow.role == "owner",
                    OrganizationMemberRow.status == "active",
                )
            )
        if owner_user_id is None:
            continue
        token = set_storage_context(WorkspaceStorageContext(actor_user_id=owner_user_id, organization_id=organization_id, storage_user_id=storage_user_id or owner_user_id))
        try:
            for seat in org_seats:
                await evaluate_seat_scorecard(repo, seat, announce=announce_to_exec)
        finally:
            reset_storage_context(token)


async def _run_seat_scorecard_loop(interval_seconds: float) -> None:
    """Recurring seat-scorecard sweep, cancelled cleanly on shutdown (queue item e11)."""
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            await _run_seat_scorecard_sweep()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Seat scorecard sweep failed")


def _start_seat_scorecard_loop(startup_config) -> asyncio.Task | None:
    """Schedule the recurring scorecard sweep when configured; ``None`` otherwise.

    Defensive against unconfigured ``startup_config`` test doubles, same as
    ``_start_seat_budget_loop``.
    """
    from deerflow.config.exec_seats_config import ExecSeatsConfig

    exec_seats_config = getattr(startup_config, "exec_seats", None)
    if not isinstance(exec_seats_config, ExecSeatsConfig) or not exec_seats_config.scorecard_check_enabled:
        return None
    return asyncio.create_task(_run_seat_scorecard_loop(exec_seats_config.scorecard_check_interval_seconds))


async def _shutdown_seat_scorecard_loop(app: FastAPI) -> None:
    """Cancel the recurring scorecard sweep task, if one was started."""
    task = getattr(app.state, "seat_scorecard_loop_task", None)
    if task is None or task.done():
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


async def _run_hire_idle_retirement_sweep() -> None:
    """One idle-probation pass over every organization's active hires (queue item e12).

    EXECUTIVE.md Hiring rule: "A hire idle 7 days ... is retired
    automatically." Same per-organization storage-context shape as
    ``_run_seat_budget_sweep``/``_run_seat_scorecard_sweep``
    (``deerflow.hiring.retirement.evaluate_hire_idle_retirement`` and its
    ``#exec`` announcement are organization-scoped via ambient
    ``resolve_organization_id()``), and the same "skip an org with no active
    owner to attribute the sweep to" posture.
    """
    from sqlalchemy import select

    from deerflow.config.hiring_config import HiringConfig
    from deerflow.hiring.retirement import evaluate_hire_idle_retirement
    from deerflow.persistence.engine import get_session_factory
    from deerflow.persistence.hiring.sql import HiredAgentRepository
    from deerflow.persistence.organizations.model import OrganizationMemberRow, OrganizationRow
    from deerflow.runtime.user_context import WorkspaceStorageContext, reset_storage_context, set_storage_context

    session_factory = get_session_factory()
    if session_factory is None:
        return
    hiring_config = getattr(get_app_config(), "hiring", None)
    idle_days = hiring_config.idle_days_before_retirement if isinstance(hiring_config, HiringConfig) else HiringConfig().idle_days_before_retirement
    repo = HiredAgentRepository(session_factory)
    hires_by_org: dict[str, list[dict]] = {}
    for hire in await repo.list_hires():
        hires_by_org.setdefault(hire["organization_id"], []).append(hire)

    for organization_id, org_hires in hires_by_org.items():
        async with session_factory() as session:
            storage_user_id = await session.scalar(select(OrganizationRow.storage_user_id).where(OrganizationRow.id == organization_id))
            owner_user_id = await session.scalar(
                select(OrganizationMemberRow.user_id).where(
                    OrganizationMemberRow.organization_id == organization_id,
                    OrganizationMemberRow.role == "owner",
                    OrganizationMemberRow.status == "active",
                )
            )
        if owner_user_id is None:
            continue
        token = set_storage_context(WorkspaceStorageContext(actor_user_id=owner_user_id, organization_id=organization_id, storage_user_id=storage_user_id or owner_user_id))
        try:
            for hire in org_hires:
                await evaluate_hire_idle_retirement(repo, hire, idle_days=idle_days, announce=_announce_to_exec_without_receipt)
        finally:
            reset_storage_context(token)


async def _run_hire_idle_retirement_loop(interval_seconds: float) -> None:
    """Recurring hire idle-retirement sweep, cancelled cleanly on shutdown (queue item e12)."""
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            await _run_hire_idle_retirement_sweep()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Hire idle-retirement sweep failed")


def _start_hire_idle_retirement_loop(startup_config) -> asyncio.Task | None:
    """Schedule the recurring sweep when configured; ``None`` otherwise.

    Defensive against unconfigured ``startup_config`` test doubles, same as
    ``_start_seat_budget_loop``.
    """
    from deerflow.config.hiring_config import HiringConfig

    hiring_config = getattr(startup_config, "hiring", None)
    if not isinstance(hiring_config, HiringConfig) or not hiring_config.retirement_check_enabled:
        return None
    return asyncio.create_task(_run_hire_idle_retirement_loop(hiring_config.retirement_check_interval_seconds))


async def _shutdown_hire_idle_retirement_loop(app: FastAPI) -> None:
    """Cancel the recurring sweep task, if one was started."""
    task = getattr(app.state, "hire_idle_retirement_loop_task", None)
    if task is None or task.done():
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


async def _run_hire_kpi_review_sweep() -> None:
    """One weekly KPI-review pass over every organization's active hires (queue item e12).

    The other half of EXECUTIVE.md's Probation rule ("missing its KPI 2
    weeks running ... is retired automatically"), alongside
    ``_run_hire_idle_retirement_sweep``. Same per-organization storage-context
    shape.
    """
    from sqlalchemy import select

    from deerflow.hiring.kpi_review import evaluate_hire_kpi
    from deerflow.persistence.engine import get_session_factory
    from deerflow.persistence.hiring.sql import HiredAgentRepository
    from deerflow.persistence.organizations.model import OrganizationMemberRow, OrganizationRow
    from deerflow.runtime.user_context import WorkspaceStorageContext, reset_storage_context, set_storage_context

    session_factory = get_session_factory()
    if session_factory is None:
        return
    repo = HiredAgentRepository(session_factory)
    hires_by_org: dict[str, list[dict]] = {}
    for hire in await repo.list_hires():
        hires_by_org.setdefault(hire["organization_id"], []).append(hire)

    for organization_id, org_hires in hires_by_org.items():
        async with session_factory() as session:
            storage_user_id = await session.scalar(select(OrganizationRow.storage_user_id).where(OrganizationRow.id == organization_id))
            owner_user_id = await session.scalar(
                select(OrganizationMemberRow.user_id).where(
                    OrganizationMemberRow.organization_id == organization_id,
                    OrganizationMemberRow.role == "owner",
                    OrganizationMemberRow.status == "active",
                )
            )
        if owner_user_id is None:
            continue
        token = set_storage_context(WorkspaceStorageContext(actor_user_id=owner_user_id, organization_id=organization_id, storage_user_id=storage_user_id or owner_user_id))
        try:
            for hire in org_hires:
                await evaluate_hire_kpi(repo, hire, announce=_announce_to_exec_without_receipt)
        finally:
            reset_storage_context(token)


async def _run_hire_kpi_review_loop(interval_seconds: float) -> None:
    """Recurring hire KPI-review sweep, cancelled cleanly on shutdown (queue item e12)."""
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            await _run_hire_kpi_review_sweep()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Hire KPI-review sweep failed")


def _start_hire_kpi_review_loop(startup_config) -> asyncio.Task | None:
    """Schedule the recurring sweep when configured; ``None`` otherwise.

    Defensive against unconfigured ``startup_config`` test doubles, same as
    ``_start_hire_idle_retirement_loop``.
    """
    from deerflow.config.hiring_config import HiringConfig

    hiring_config = getattr(startup_config, "hiring", None)
    if not isinstance(hiring_config, HiringConfig) or not hiring_config.kpi_check_enabled:
        return None
    return asyncio.create_task(_run_hire_kpi_review_loop(hiring_config.kpi_check_interval_seconds))


async def _shutdown_hire_kpi_review_loop(app: FastAPI) -> None:
    """Cancel the recurring sweep task, if one was started."""
    task = getattr(app.state, "hire_kpi_review_loop_task", None)
    if task is None or task.done():
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler."""

    # Load config and check necessary environment variables at startup.
    # `startup_config` is a local snapshot used only for one-shot bootstrap
    # work (logging level, langgraph_runtime engines, channels). Request-time
    # config resolution always routes through `get_app_config()` in
    # `app/gateway/deps.py::get_config()` so `config.yaml` edits become
    # visible without a process restart. We deliberately do NOT cache this
    # snapshot on `app.state` to keep that contract enforceable.
    try:
        startup_config = get_app_config()
        from deerflow.config.subagent_batches_config import SubagentBatchesConfig
        from deerflow.config.subagent_runtime_config import SubagentRuntimeConfig
        from deerflow.subagents.capacity import configure_subagent_execution_capacity

        subagent_runtime_config = getattr(startup_config, "subagent_runtime", None)
        if not isinstance(subagent_runtime_config, SubagentRuntimeConfig):
            subagent_runtime_config = SubagentRuntimeConfig()
        subagent_batches_config = getattr(startup_config, "subagent_batches", None)
        if not isinstance(subagent_batches_config, SubagentBatchesConfig):
            subagent_batches_config = SubagentBatchesConfig()
        configure_subagent_execution_capacity(subagent_runtime_config)
        configure_logging(startup_config)
        ensure_browser_runtime_available(startup_config)
        logger.info("Configuration loaded successfully")
        warn_if_auth_disabled_enabled()
    except Exception as e:
        error_msg = f"Failed to load configuration during gateway startup: {e}"
        logger.exception(error_msg)
        raise RuntimeError(error_msg) from e
    config = get_gateway_config()
    logger.info(f"Starting API Gateway on {config.host}:{config.port}")

    # The Jevbox preparation route is disabled unless a strict, bounded
    # startup-owned binding is explicitly configured. Never log its path or
    # contents, and fail startup closed when an opted-in binding is invalid.
    from app.gateway.jevbox_preparation_binding import (
        JevboxPreparationBindingError,
        load_optional_jevbox_preparation_binding,
    )

    try:
        app.state.jevbox_preparation_binding = await asyncio.to_thread(load_optional_jevbox_preparation_binding)
    except JevboxPreparationBindingError:
        logger.error("Jevbox preparation binding rejected; startup stopped")
        raise RuntimeError("Jevbox preparation binding invalid") from None

    from deerflow.skills.projection import ensure_public_skill_projection

    public_projection_ready = await asyncio.to_thread(ensure_public_skill_projection, app_config=startup_config)
    if public_projection_ready:
        logger.info("Ensured the public skill projection; user projections repair lazily on sandbox acquire")

    # Agent observability (Monocle). Off by default; enabled with
    # MONOCLE_TRACING. Initialized here at startup — not at import time — so a
    # plain `import deerflow.agents` never installs a process-global tracer.
    # Unlike LangSmith/Langfuse, whose validation failures abort the agent run,
    # a bad Monocle config only logs: the Gateway keeps serving without tracing.
    try:
        setup_monocle_tracing_if_enabled()
    except Exception:  # observability must never break startup
        logger.exception("Monocle tracing setup failed; continuing without it")

    # Rebuild the derived memory retrieval index in the background. Scoped
    # searches remain correct while this runs because DeerMem lazily rebuilds
    # the requested scope when the full warm-up has not completed yet.
    retrieval_warm_task: asyncio.Task[None] | None = None
    try:
        from deerflow.agents.memory import get_memory_manager

        if startup_config.memory.enabled:
            manager = await asyncio.to_thread(get_memory_manager)
            warm_retrieval = getattr(manager, "warm_retrieval", None)
            if callable(warm_retrieval):
                retrieval_warm_task = asyncio.create_task(
                    _warm_memory_retrieval(manager),
                    name="memory-retrieval-warm-up",
                )
        else:
            logger.info("Memory is disabled; skipping retrieval index rebuild")
    except Exception:
        logger.warning("Memory retrieval index rebuild skipped", exc_info=True)

    # Pre-warm tiktoken encoding cache so the first memory-injection request
    # never blocks on the BPE data download (which hits an OpenAI/Azure URL
    # that may be unreachable in restricted networks — see issue #3402).
    # Warm-up runs via the manager's `warm()` tier-3 hook. DeerMem.warm re-checks
    # token_counting=="char" and returns early, so char-mode backends never touch
    # tiktoken (avoids even the 5s probe in network-restricted deployments - see
    # issue #3429). A backend with nothing to warm (e.g. noop) returns None from
    # the base default -- log "skipping" instead of the misleading "warmed
    # successfully" so the log reflects what actually happened.
    try:
        from deerflow.agents.memory import get_memory_manager

        manager = await asyncio.to_thread(get_memory_manager)
        warmed = await asyncio.wait_for(
            asyncio.to_thread(manager.warm),
            timeout=5,
        )
        if warmed is None:
            logger.info("Memory backend %s has nothing to warm; skipping tiktoken warm-up", type(manager).__name__)
        elif warmed:
            logger.info("tiktoken encoding cache warmed successfully")
        else:
            logger.warning("tiktoken encoding cache warm-up failed; token counting will use character-based fallback until tiktoken loads successfully")
    except TimeoutError:
        logger.warning("tiktoken encoding cache warm-up timed out; token counting will use character-based fallback until tiktoken loads successfully")
    except Exception:
        logger.warning("tiktoken warm-up skipped", exc_info=True)

    try:
        removed_upload_staging_files = await asyncio.to_thread(cleanup_stale_upload_staging_files)
        if removed_upload_staging_files:
            logger.info("Removed %d stale upload staging file(s)", removed_upload_staging_files)
    except Exception:
        logger.warning("Upload staging file cleanup skipped", exc_info=True)

    # Initialize LangGraph runtime components (StreamBridge, RunManager, checkpointer, store)
    async with langgraph_runtime(app, startup_config):
        logger.info("LangGraph runtime initialised")

        # Check admin bootstrap state and migrate orphan threads after admin exists.
        # Must run AFTER langgraph_runtime so app.state.store is available for thread migration
        await _ensure_admin_user(app)

        # Phase-2 trash tier (§8.3): one retention sweep at startup, beside
        # the lazy trigger on the trash listing — no daemon, no scheduler.
        # Runs after langgraph_runtime so app.state.project_document_repo is
        # available. The per-user reconciliation walks every row and file, so
        # it is scheduled as a background task: gateway readiness never waits
        # on it, a failure is logged by the task itself, and shutdown gives the
        # in-flight sweep a bounded graceful budget before cancelling it; any
        # already-started file worker drains before the runtime is torn down.
        app.state.startup_trash_sweep_task = asyncio.create_task(_run_startup_trash_sweep(app, startup_config))

        # Queue item f95: recurring weekly-budget pause/resume sweep for
        # Momentum agent seats, off by default (config.exec_seats.budget_check_enabled).
        app.state.seat_budget_loop_task = _start_seat_budget_loop(startup_config)

        # Queue item e11: recurring weekly-scorecard sweep for Momentum agent
        # seats, off by default (config.exec_seats.scorecard_check_enabled).
        app.state.seat_scorecard_loop_task = _start_seat_scorecard_loop(startup_config)

        # Queue item e12: recurring idle-probation sweep for Momentum agent
        # hires, off by default (config.hiring.retirement_check_enabled).
        app.state.hire_idle_retirement_loop_task = _start_hire_idle_retirement_loop(startup_config)

        # Queue item e12: recurring KPI-review sweep for Momentum agent
        # hires, off by default (config.hiring.kpi_check_enabled).
        app.state.hire_kpi_review_loop_task = _start_hire_kpi_review_loop(startup_config)

        try:
            from app.gateway.services import launch_scheduled_thread_run
            from app.scheduler import ScheduledTaskService

            if getattr(app.state, "scheduled_task_repo", None) is not None and getattr(app.state, "scheduled_task_run_repo", None) is not None:
                scheduled_task_service = ScheduledTaskService(
                    task_repo=app.state.scheduled_task_repo,
                    task_run_repo=app.state.scheduled_task_run_repo,
                    launch_run=lambda **kwargs: launch_scheduled_thread_run(app=app, **kwargs),
                    poll_interval_seconds=startup_config.scheduler.poll_interval_seconds,
                    lease_seconds=startup_config.scheduler.lease_seconds,
                    max_concurrent_runs=startup_config.scheduler.max_concurrent_runs,
                    queue_timeout_seconds=startup_config.scheduler.queue_timeout_seconds,
                    multi_instance=startup_config.scheduler.multi_instance,
                    run_lease_grace_seconds=startup_config.run_ownership.grace_seconds,
                )
                app.state.scheduled_task_service = scheduled_task_service
                if startup_config.scheduler.enabled:
                    await scheduled_task_service.start()
        except Exception:
            logger.exception("Failed to initialize scheduled task service")
            # If an enabled scheduler rejects start(), keep that rejection as a
            # lifespan failure instead of exposing a half-started service.
            if startup_config.scheduler.enabled:
                raise

        # Start IM channel service only after scheduler recovery succeeds, so a
        # fail-closed scheduler startup cannot strand channel-owned tasks before
        # the lifespan reaches its normal shutdown boundary.
        try:
            from app.channels.service import start_channel_service

            # Closure over `app` (mirrors ScheduledTaskService's `launch_run`
            # above) rather than resolving `app.state.stream_bridge` here
            # directly: `stream_bridge` is a STARTUP_ONLY_FIELDS singleton set
            # once, above, by `langgraph_runtime(app, startup_config)`, so
            # either shape is safe by construction — the closure is just the
            # more defensive/consistent-with-precedent form, and it is what
            # ChannelManager's follow-up-drain watcher (issue #4121 Slice 2)
            # uses to reach the same StreamBridge every other run consumer
            # goes through `get_stream_bridge(request)` for.
            channel_service = await start_channel_service(
                startup_config,
                get_stream_bridge=lambda: getattr(app.state, "stream_bridge", None),
            )
            logger.info("Channel service started: %s", channel_service.get_status())
        except Exception:
            logger.exception("No IM channels configured or channel service failed to start")

        from app.gateway.services import launch_mcp_task_notification_run
        from app.mcp_tasks import McpTaskService
        from deerflow.config.extensions_config import ExtensionsConfig
        from deerflow.config.mcp_tasks_config import McpTasksConfig
        from deerflow.mcp.task_tool_caller import McpTaskToolCaller
        from deerflow.mcp.tasks import (
            ORDINARY_MCP_TASK_DRIVER,
            McpTaskDriverRegistry,
            OrdinaryMcpTaskDriver,
        )
        from deerflow.mcp.tasks.runtime import (
            configured_task_toolset_count,
            set_mcp_task_config_snapshot,
            set_mcp_task_submitter,
            validate_mcp_task_runtime_configuration,
        )

        task_extensions_config = ExtensionsConfig.from_file()
        mcp_tasks_config = getattr(startup_config, "mcp_tasks", McpTasksConfig())
        mcp_task_repo = getattr(app.state, "mcp_task_repo", None)
        app.state.mcp_tasks_available = False
        set_mcp_task_submitter(None)
        set_mcp_task_config_snapshot(task_extensions_config)
        validate_mcp_task_runtime_configuration(
            mcp_tasks_config=mcp_tasks_config,
            extensions_config=task_extensions_config,
            repository_available=mcp_task_repo is not None,
        )
        if mcp_task_repo is not None:
            mcp_task_drivers = McpTaskDriverRegistry()
            if configured_task_toolset_count(task_extensions_config):
                mcp_task_drivers.register(
                    ORDINARY_MCP_TASK_DRIVER,
                    OrdinaryMcpTaskDriver(McpTaskToolCaller(task_extensions_config)),
                )
            mcp_task_service = McpTaskService(
                repository=mcp_task_repo,
                drivers=mcp_task_drivers,
                poll_interval_seconds=mcp_tasks_config.poll_interval_seconds,
                lease_seconds=mcp_tasks_config.lease_seconds,
                max_concurrent_polls=mcp_tasks_config.max_concurrent_polls,
                max_poll_backoff_seconds=mcp_tasks_config.max_poll_backoff_seconds,
                input_required_poll_interval_seconds=mcp_tasks_config.input_required_poll_interval_seconds,
                tracking_degraded_after_errors=mcp_tasks_config.tracking_degraded_after_errors,
                max_result_bytes=mcp_tasks_config.max_result_bytes,
                result_preview_max_chars=mcp_tasks_config.result_preview_max_chars,
                launch_notification=lambda **kwargs: launch_mcp_task_notification_run(app=app, **kwargs),
                get_run=lambda run_id, **kwargs: app.state.run_manager.get(
                    run_id,
                    raise_on_store_error=True,
                    **kwargs,
                ),
            )
            app.state.mcp_task_drivers = mcp_task_drivers
            app.state.mcp_task_service = mcp_task_service
            if mcp_tasks_config.enabled:
                await mcp_task_service.start()
                set_mcp_task_submitter(mcp_task_service)
                app.state.mcp_tasks_available = True

        from app.subagent_batches import SubagentBatchService
        from deerflow.subagents.batch_runtime import set_subagent_batch_submitter

        batch_repo = getattr(app.state, "subagent_batch_repo", None)
        app.state.subagent_batches_available = False
        # Fleet hosts read lease and result limits from the same config (routers/fleet_work.py).
        app.state.subagent_batches_config = subagent_batches_config
        # Desktop-lane submissions are checked against the Slack roster (routers/fleet_work.py).
        app.state.roster_config = getattr(startup_config, "roster", None)
        set_subagent_batch_submitter(None)
        if subagent_batches_config.enabled and batch_repo is None:
            raise RuntimeError("subagent_batches.enabled requires database.backend sqlite or postgres")
        if batch_repo is not None:
            batch_service = SubagentBatchService(
                repository=batch_repo,
                config=subagent_batches_config,
                runtime_config=subagent_runtime_config,
                extensions=getattr(app.state, "extensions", None),
            )
            app.state.subagent_batch_service = batch_service
            if subagent_batches_config.enabled:
                await batch_service.start()
                set_subagent_batch_submitter(batch_service)
                app.state.subagent_batches_available = True

        from app.gateway.openai_agent_service import OpenAIAgentService
        from deerflow.config.paths import get_paths

        app.state.openai_agent_service = OpenAIAgentService(get_paths().base_dir / "openai-agents.sqlite")
        await app.state.openai_agent_service.start()

        from app.gateway.browserbase_service import BrowserbaseResearchService

        if BrowserbaseResearchService.enabled():
            app.state.browserbase_service = BrowserbaseResearchService(get_paths().base_dir / "browserbase-research.sqlite")
            await app.state.browserbase_service.start()

        from app.gateway.workflow_service import WorkflowService

        if WorkflowService.enabled():
            from app.gateway.workflow_authority import workflow_actor_authorized
            from app.gateway.workflow_hai_budget import create_workflow_model_adapter

            app.state.workflow_service = WorkflowService(
                get_paths().base_dir / "workflows.sqlite",
                checkpointer=app.state.checkpointer,
                adapter=create_workflow_model_adapter(startup_config),
                browser_service=getattr(app.state, "browserbase_service", None),
                run_manager=app.state.run_manager,
                thread_store=app.state.thread_store,
                event_store=app.state.run_event_store,
                authority=workflow_actor_authorized,
            )
            await app.state.workflow_service.start()

        yield

        await _shutdown_startup_trash_sweep(app)
        await _shutdown_seat_budget_loop(app)
        await _shutdown_seat_scorecard_loop(app)
        await _shutdown_hire_idle_retirement_loop(app)
        await _shutdown_hire_kpi_review_loop(app)

        if getattr(app.state, "workflow_service", None) is not None:
            await app.state.workflow_service.aclose()

        if getattr(app.state, "browserbase_service", None) is not None:
            try:
                await app.state.browserbase_service.aclose()
            except Exception:
                logger.exception("Failed to close Browserbase research client")

        if getattr(app.state, "openai_agent_service", None) is not None:
            try:
                await app.state.openai_agent_service.aclose()
            except Exception:
                logger.exception("Failed to close OpenAI agent HTTP client")

        try:
            await auth.close_oidc_service()
        except Exception:
            logger.exception("Failed to close OIDC service")

        # Stop channel service on shutdown (bounded to prevent worker hang)
        try:
            from app.channels.service import stop_channel_service

            await asyncio.wait_for(
                stop_channel_service(),
                timeout=_SHUTDOWN_HOOK_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            logger.warning(
                "Channel service shutdown exceeded %.1fs; proceeding with worker exit.",
                _SHUTDOWN_HOOK_TIMEOUT_SECONDS,
            )
        except Exception:
            logger.exception("Failed to stop channel service")

        if getattr(app.state, "scheduled_task_service", None) is not None:
            try:
                await app.state.scheduled_task_service.stop()
            except Exception:
                logger.exception("Failed to stop scheduled task service")

        if getattr(app.state, "mcp_task_service", None) is not None:
            app.state.mcp_tasks_available = False
            try:
                await app.state.mcp_task_service.stop()
            except Exception:
                logger.exception("Failed to stop MCP task service")
            finally:
                from deerflow.mcp.tasks.runtime import set_mcp_task_submitter

                set_mcp_task_submitter(None)
        from deerflow.mcp.tasks.runtime import set_mcp_task_config_snapshot

        set_mcp_task_config_snapshot(None)

        if getattr(app.state, "subagent_batch_service", None) is not None:
            app.state.subagent_batches_available = False
            try:
                await app.state.subagent_batch_service.stop()
            except Exception:
                logger.exception("Failed to stop subagent batch service")
            finally:
                from deerflow.subagents.batch_runtime import set_subagent_batch_submitter

                set_subagent_batch_submitter(None)

        try:
            from deerflow.community.browser_automation import get_browser_session_manager

            closed = await asyncio.wait_for(
                get_browser_session_manager().close_all_sessions(),
                timeout=_SHUTDOWN_HOOK_TIMEOUT_SECONDS,
            )
            if closed:
                logger.info("Closed %d browser session(s)", closed)
        except TimeoutError:
            logger.warning(
                "Browser session shutdown exceeded %.1fs; proceeding with worker exit.",
                _SHUTDOWN_HOOK_TIMEOUT_SECONDS,
            )
        except Exception:
            logger.exception("Failed to close browser sessions")

        # Drain the memory backend's pending-update buffer before the worker
        # exits (best-effort, bounded). IM channels and the scheduler are
        # already stopped above, so no new IM/scheduler updates arrive during
        # the drain; the LangGraph runtime / in-flight HTTP requests can still
        # complete memory enqueues in a narrow window, but anything added after
        # the drain copies the buffer only resets the debounce Timer
        # (best-effort, same as today).
        #
        # No host-level pending/processing guard: ``shutdown_flush``
        # short-circuits on a truly idle buffer (returns True immediately), so
        # calling it unconditionally is cheap and keeps the in-flight-worker
        # race entirely inside the backend (where the buffer lives) -- the host
        # cannot "forget" that case the way a ``pending_count > 0``-only guard
        # would (review #6 on the original PR).
        #
        # K8s caveat: ``shutdown_flush_timeout_seconds`` must fit inside the
        # pod's ``terminationGracePeriodSeconds`` (channel stop + browser
        # session close + the brief retrieval-warm wait + config/backend
        # resolution + this drain + backend close + buffer),
        # set on the gateway Helm deployment -- or K8s SIGKILLs the drain
        # mid-flight and the loss this is fixing is silently re-introduced.
        # Backend close has no host timeout: overrides must be quick or
        # internally bounded, since cancellation waits for that worker too.
        # The retrieval index is derived from canonical memory files, so its
        # wait is independently capped and never consumes the flush budget.
        retrieval_warm_finished = True
        if retrieval_warm_task is not None and not retrieval_warm_task.done():
            try:
                await asyncio.wait_for(
                    asyncio.shield(retrieval_warm_task),
                    timeout=min(
                        _RETRIEVAL_WARM_SHUTDOWN_TIMEOUT_SECONDS,
                        startup_config.memory.shutdown_flush_timeout_seconds,
                    ),
                )
            except TimeoutError:
                retrieval_warm_finished = False
                logger.warning("Memory retrieval index rebuild is still running; leaving its connection open during shutdown")

        try:
            # Memory shutdown runs on worker threads and can trigger detached
            # system-model callbacks. Stop accepting those callbacks before
            # flushing, while keeping the registered loop alive for awaited
            # task hooks until langgraph_runtime drains runs and subagents.
            from deerflow.extensions.notify import suspend_extension_system_observations

            suspend_extension_system_observations()
        except Exception:
            logger.debug("Failed to suspend extension system observations (non-fatal)", exc_info=True)

        # ``asyncio.to_thread`` cancellation only detaches the awaiter; the
        # worker keeps running. Treat resolve + flush + close as one owned
        # shutdown operation so lifespan cancellation cannot close the backend
        # underneath an in-flight flush or return while either worker is live.
        await await_drained(
            _shutdown_memory_backend(
                retrieval_warm_finished=retrieval_warm_finished,
            )
        )

    logger.info("Shutting down API Gateway")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns:
        Configured FastAPI application instance.
    """
    config = get_gateway_config()
    docs_url = "/docs" if config.enable_docs else None
    redoc_url = "/redoc" if config.enable_docs else None
    openapi_url = "/openapi.json" if config.enable_docs else None

    app = FastAPI(
        title="DeerFlow API Gateway",
        description="""
## DeerFlow API Gateway

API Gateway for DeerFlow - A LangGraph-based AI agent backend with sandbox execution capabilities.

### Features

- **Models Management**: Query and retrieve available AI models
- **MCP Configuration**: Manage Model Context Protocol (MCP) server configurations
- **Memory Management**: Access and manage global memory data for personalized conversations
- **Skills Management**: Query and manage skills and their enabled status
- **Artifacts**: Access thread artifacts and generated files
- **Health Monitoring**: System health check endpoints

### Architecture

LangGraph-compatible requests are routed through nginx to this gateway.
This gateway provides runtime endpoints for agent runs plus custom endpoints for models, MCP configuration, skills, and artifacts.
        """,
        version="0.1.0",
        lifespan=lifespan,
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
        openapi_tags=[
            {
                "name": "models",
                "description": "Operations for querying available AI models and their configurations",
            },
            {
                "name": "mcp",
                "description": "Manage Model Context Protocol (MCP) server configurations",
            },
            {
                "name": "memory",
                "description": "Access and manage global memory data for personalized conversations",
            },
            {
                "name": "skills",
                "description": "Manage skills and their configurations",
            },
            {
                "name": "artifacts",
                "description": "Access and download thread artifacts and generated files",
            },
            {
                "name": "uploads",
                "description": "Upload and manage user files for threads",
            },
            {
                "name": "threads",
                "description": "Manage DeerFlow thread-local filesystem data",
            },
            {
                "name": "agents",
                "description": "Create and manage custom agents with per-agent config and prompts",
            },
            {
                "name": "suggestions",
                "description": "Generate follow-up question suggestions for conversations",
            },
            {
                "name": "input-polish",
                "description": "Polish composer draft input before sending",
            },
            {
                "name": "channels",
                "description": "Manage IM channel integrations (Feishu, Slack, Telegram)",
            },
            {
                "name": "assistants-compat",
                "description": "LangGraph Platform-compatible assistants API (stub)",
            },
            {
                "name": "runs",
                "description": "LangGraph Platform-compatible runs lifecycle (create, stream, cancel)",
            },
            {
                "name": "health",
                "description": "Health check and system status endpoints",
            },
        ],
    )

    # Auth: reject unauthenticated requests to non-public paths (fail-closed safety net)
    app.add_middleware(AuthMiddleware)

    # Give contributed routers a neutral way to ask "is this caller an admin"
    # without importing app.gateway.deps, which would pin them to an
    # unpublished internal layer and defeat independent distribution. The
    # resolver mirrors require_admin_user's primary path (deps.py): it reads
    # request.state.user, which AuthMiddleware stamps before any router runs,
    # rather than the async get_current_user_from_request/get_optional_user_from_request
    # accessors that exist for tests and alternative ASGI compositions. Staying
    # synchronous keeps resolve_principal/require_admin usable from both sync
    # and async route handlers.
    def _resolve_extension_principal(request):
        """Project the host's auth context into the neutral extension shape.

        Deliberately a projection, not a handle: an extension gets the
        questions it may ask (who, is that an admin, and what role they
        hold), not the host's AuthContext, which would pin every extension to
        its internals.
        """
        user = getattr(request.state, "user", None)
        if user is None:
            return None
        system_role = getattr(user, "system_role", None)
        # PAT credentials never carry admin capability (#5041): suppress every
        # admin signal — both ``is_admin`` and the ``admin`` role — so an
        # admin-owned PAT cannot regain admin through extension-side
        # require_admin, mirroring deps.is_admin_user's PAT guard.
        auth_source = getattr(request.state, "auth_source", None)
        is_pat = auth_source == AUTH_SOURCE_PAT
        is_admin = system_role == "admin" and not is_pat
        roles = () if is_pat and system_role == "admin" else (system_role,) if isinstance(system_role, str) and system_role else ()
        return ExtensionPrincipal(
            user_id=str(user.id),
            is_admin=is_admin,
            is_internal=auth_source == AUTH_SOURCE_INTERNAL,
            # The host's only role concept is the single system_role column
            # (e.g. "admin", "user") — there is no multi-role system to
            # project, so a set role becomes the one-element tuple rather
            # than reading a "roles" attribute the user model never had.
            roles=roles,
        )

    setattr(app.state, EXTENSION_PRINCIPAL_RESOLVER_KEY, _resolve_extension_principal)

    # CSRF: Double Submit Cookie pattern for state-changing requests
    app.add_middleware(CSRFMiddleware)

    # CORS: the unified nginx endpoint is same-origin by default. Split-origin
    # browser clients must opt in with this explicit Gateway allowlist so CORS
    # and CSRF origin checks share the same source of truth. They also need the
    # run id the Gateway returns in a non-safelisted response header; without
    # exposing it the SDK never reports a created run, so a new thread keeps its
    # placeholder route and every action gated on an established thread stays
    # hidden until the page is reloaded.
    cors_origins = sorted(get_configured_cors_origins())
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=list(CORS_EXPOSED_HEADERS),
        )

    # Request trace correlation: bind one trace id per Gateway HTTP request
    # and write it to the response start headers. Ungated, so it works without
    # a config.yaml and needs no restart; logging.enhance.enabled only decides
    # whether that id is printed into log records.
    app.add_middleware(TraceMiddleware)

    # Python extensions load once while the Gateway app is constructed. Agent
    # middleware builders consume the same immutable set through the process
    # singleton; app.state exposes it to the Gateway runtime.
    from deerflow.extensions import (
        EMPTY_EXTENSIONS,
        ExtensionLoadError,
        initialize_runtime_diagnostics,
        load_extensions,
        record_runtime_diagnostics,
        set_loaded_extensions,
    )

    # Resolving the configured plugin list is deliberately outside the
    # fail-open guard below: a config.yaml that exists but cannot be parsed or
    # validated is a configuration failure, not an extension failure. Reporting
    # it as the latter would silently drop a `required: true` extension instead
    # of failing the boot. Only an absent config.yaml is tolerated — create_app()
    # runs at import time, and lifespan still performs strict config loading
    # before serving.
    try:
        configured_plugins = get_app_config().plugins
    except FileNotFoundError:
        logger.debug("config.yaml not found while constructing Gateway app; loading no extensions for this app instance")
        configured_plugins = []

    try:
        loaded_extensions, extension_diagnostics = load_extensions(configured_plugins)
    except ExtensionLoadError:
        # `required: true` makes the extension part of the startup contract.
        # Booting without it would silently change configured behaviour.
        raise
    except Exception:
        logger.exception("Extension loading failed; continuing with no extensions")
        loaded_extensions, extension_diagnostics = EMPTY_EXTENSIONS, []
    set_loaded_extensions(loaded_extensions)
    app.state.extensions = loaded_extensions
    app.state.extension_diagnostics = initialize_runtime_diagnostics(extension_diagnostics)

    # Include routers
    # Models API is mounted at /api/models
    from app.gateway.routers import managed_models

    app.include_router(managed_models.router)
    app.include_router(models.router)
    app.include_router(openai_agents.router)
    app.include_router(browserbase_research.router)
    app.include_router(workflows.router)

    # Features API is mounted at /api/features
    app.include_router(features.router)
    app.include_router(agent_room.router)

    # Console API (cross-thread observability) is mounted at /api/console
    app.include_router(console.router)
    app.include_router(cost_router.router)
    app.include_router(command_center.router)

    # MCP API is mounted at /api/mcp
    app.include_router(capabilities.router)
    app.include_router(mcp.router)

    # Durable MCP tasks are scoped to their owning thread.
    app.include_router(mcp_tasks.router)
    app.include_router(subagent_batches.router)
    app.include_router(fleet_work.router)

    # Memory API is mounted at /api/memory
    app.include_router(memory.router)

    # Skills API is mounted at /api/skills
    app.include_router(skills.router)

    # First-party integrations API is mounted at /api/integrations
    app.include_router(integrations.router)
    app.include_router(composio_connect.router)

    # Read-only RAGFlow catalog for chat knowledge-scope selection.
    app.include_router(knowledge.router)

    # Artifacts API is mounted at /api/threads/{thread_id}/artifacts
    app.include_router(artifacts.router)
    app.include_router(wsl_diagnostics.router)

    # Browser API is mounted at /api/threads/{thread_id}/browser
    app.include_router(browser.router)

    # Uploads API is mounted at /api/threads/{thread_id}/uploads
    app.include_router(uploads.router)

    # Thread cleanup API is mounted at /api/threads/{thread_id}
    app.include_router(threads.router)

    # Scheduled tasks API is mounted at /api/scheduled-tasks
    app.include_router(scheduled_tasks.router)

    # Agents API is mounted at /api/agents
    app.include_router(agents.router)
    # Projects API is mounted at /api/projects
    app.include_router(projects.router)
    # Project document shelf API is mounted at /api/projects/{id}/documents
    app.include_router(project_documents.router)
    # Project conversation-files view is mounted at /api/projects/{id}/thread-files
    app.include_router(project_thread_files.router)
    # Trash API is mounted at /api/trash
    app.include_router(trash.router)
    # Client roster API (+ admin registry import) is mounted at /api/clients
    app.include_router(clients.router)
    app.include_router(client_portal.router)
    # Momo Board API (client posts/tickets/concerns/DMs) is mounted at /api/board
    app.include_router(board.router)

    # Approvals inbox (agent-proposed outbound actions) is mounted at /api/approvals
    app.include_router(approvals.router)
    # Momentum-internal, staff only (private instance + staff role, else 404):
    # team channels at /api/team and the AI Academy at /api/academy
    app.include_router(team_board.router)
    app.include_router(academy.router)
    # Fleet template catalog (read-only) is mounted at /api/fleet
    app.include_router(fleet.router)

    # Deployment-level subagent catalog and admin management.
    app.include_router(subagents.router)

    # Suggestions API is mounted at /api/threads/{thread_id}/suggestions
    app.include_router(suggestions.router)

    # Input polishing API is mounted at /api/input-polish
    app.include_router(input_polish.router)

    # User-facing IM channel connection API is mounted at /api/channels
    app.include_router(channel_connections.router)

    # Channels API is mounted at /api/channels
    app.include_router(channels.router)

    # Assistants compatibility API (LangGraph Platform stub)
    app.include_router(assistants_compat.router)

    app.include_router(plugins.router)

    # Auth API is mounted at /api/v1/auth
    app.include_router(auth.router)
    app.include_router(invitations.router)
    app.include_router(workspaces.router)
    app.include_router(workspace_branding.router)
    app.include_router(momobot_brand.router)
    app.include_router(user_preferences.router)
    app.include_router(onboarding.router)

    # System-admin controls (user disable/enable/force-logout, audit log) are
    # mounted at /api/admin
    app.include_router(admin.router)

    # Feedback API is mounted at /api/threads/{thread_id}/runs/{run_id}/feedback
    app.include_router(feedback.router)

    # Thread Runs API (LangGraph Platform-compatible runs lifecycle)
    app.include_router(thread_runs.router)

    # Stateless Runs API (stream/wait without a pre-existing thread)
    app.include_router(runs.router)

    # GitHub webhooks API is mounted at /api/webhooks/github
    # Exempt from auth and CSRF middleware (see auth_middleware._PUBLIC_PATH_PREFIXES
    # and csrf_middleware.should_check_csrf); authenticity is enforced via the
    # X-Hub-Signature-256 HMAC against GITHUB_WEBHOOK_SECRET.
    # Including this router transitively imports app.gateway.github, which
    # registers the GitHub channel's ChannelRunPolicy as an import side-effect.
    #
    # Fail-closed: only mount the route when a webhook secret is configured
    # (or when the explicit DEER_FLOW_ALLOW_UNVERIFIED_GITHUB_WEBHOOKS=1
    # dev opt-in is set). A misconfigured deployment without a secret cannot
    # serve forged deliveries because the URL responds 404 — there is no
    # handler to reach.
    if github_webhooks.is_route_enabled():
        app.include_router(github_webhooks.router)
        logger.info("GitHub webhooks route mounted at /api/webhooks/github")
    else:
        logger.warning("GitHub webhooks route NOT mounted: GITHUB_WEBHOOK_SECRET unset and DEER_FLOW_ALLOW_UNVERIFIED_GITHUB_WEBHOOKS not set. /api/webhooks/github will respond 404. Configure either env var to enable the route.")

    @app.get("/health", tags=["health"])
    async def health_check() -> dict[str, str]:
        """Health check endpoint.

        Returns:
            Service health status information.
        """
        return {"status": "healthy", "service": "deer-flow-gateway"}

    @app.get("/health/ready", tags=["health"])
    async def readiness_check(request: Request, response: Response) -> dict[str, str]:
        """Readiness endpoint: 200 when the persistence backends are reachable.

        Probes the ORM engine behind ``database:`` and the effective LangGraph
        checkpointer/Store backend (legacy ``checkpointer:`` section, otherwise
        derived from ``database:``) concurrently beneath one bounded deadline.
        The checkpointer config comes from the startup snapshot recorded by
        ``langgraph_runtime`` (never hot-reloaded config), so orchestrators can
        gate on the gateway actually being ready rather than merely alive.
        Returns 503 with ``status: degraded`` when either probe fails or the
        startup backend cannot be resolved.
        """
        checkpointer_config = getattr(request.app.state, READINESS_CHECKPOINTER_CONFIG_ATTR, None)
        status_code, payload = await readiness_payload(checkpointer_config)
        response.status_code = status_code
        return payload

    # Extension routes are deliberately last: FastAPI/Starlette dispatches in
    # registration order, so every host route (including conditional routes
    # and /health) keeps precedence. Definite shadows are rejected with an
    # attributed diagnostic while unrelated extension routers still mount.
    from deerflow.extensions.gateway import include_contributed_routers

    record_runtime_diagnostics(include_contributed_routers(app, loaded_extensions))

    return app


# Create app instance for uvicorn
app = create_app()
````

## backend/packages/extension-api/deerflow_extension_api/auth.py

````python
"""The caller's identity, for contributed routes.

Contributed routers are constructed during install(), long before any request
exists, so identity cannot be handed to them at registration time. The host
instead installs a resolver on ``app.state`` and this module reads it back.

``request`` is duck-typed rather than annotated as a Starlette Request: this
package must not depend on a web framework.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

EXTENSION_PRINCIPAL_RESOLVER_KEY = "deerflow_extension_principal_resolver"


@dataclass(frozen=True)
class ExtensionPrincipal:
    user_id: str
    is_admin: bool = False
    is_internal: bool = False
    roles: tuple[str, ...] = field(default_factory=tuple)


def resolve_principal(request: object) -> ExtensionPrincipal | None:
    """Return the caller's principal, or ``None`` when it cannot be determined."""
    app = getattr(request, "app", None)
    state = getattr(app, "state", None)
    resolver = getattr(state, EXTENSION_PRINCIPAL_RESOLVER_KEY, None)
    if not callable(resolver):
        return None
    try:
        principal = resolver(request)
    except Exception as exc:  # noqa: BLE001 - an unanswerable identity is not an error to propagate
        logger.warning("extension principal resolver failed: %s", type(exc).__name__)
        return None
    return principal if isinstance(principal, ExtensionPrincipal) else None


def require_admin(request: object) -> ExtensionPrincipal:
    """Return the principal when it is an admin, else raise ``PermissionError``.

    Fails closed on an absent or failing resolver: an authorization question the
    host cannot answer must never resolve to "allowed".
    """
    principal = resolve_principal(request)
    if principal is None or not principal.is_admin:
        raise PermissionError("this endpoint requires an administrator account")
    return principal
````

## backend/packages/harness/deerflow/persistence/organizations/resolution.py

````python
"""Small server-side organization resolution helpers for the dual-write window."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from deerflow.persistence.organizations.identity import private_organization_id
from deerflow.persistence.organizations.model import OrganizationMemberRow, OrganizationRow
from deerflow.persistence.user.model import UserRow


class _OwnedRow(Protocol):
    user_id: str | None
    organization_id: str | None


@dataclass(frozen=True, slots=True)
class ActiveOrganization:
    """Server-validated organization membership and storage principal."""

    id: str
    name: str
    role: str
    storage_user_id: str | None


async def active_organization_for_user(
    session: AsyncSession,
    user_id: str | None,
    organization_id: str | None = None,
) -> ActiveOrganization | None:
    """Resolve one active organization selected by an authenticated actor.

    A missing selector means the actor's deterministic private organization.
    An explicit selector is accepted only with an active membership row. The
    nullable storage principal is intentional: private organizations continue
    to use the actor's id, while shared organizations provide a dedicated
    principal.
    """
    if user_id is None:
        return None
    target_id = organization_id or private_organization_id(user_id)
    row = (
        await session.execute(
            select(OrganizationRow, OrganizationMemberRow.role)
            .join(
                OrganizationMemberRow,
                (OrganizationMemberRow.organization_id == OrganizationRow.id) & (OrganizationMemberRow.user_id == user_id),
            )
            .where(
                OrganizationRow.id == target_id,
                OrganizationRow.status == "active",
                OrganizationMemberRow.status == "active",
                # A disabled account keeps no organization, which closes its
                # sessions, PATs and internal delegations in this one place.
                ~exists().where(UserRow.id == user_id, UserRow.disabled_at.is_not(None)),
            )
        )
    ).first()
    if row is None:
        return None
    organization, role = row
    return ActiveOrganization(
        id=organization.id,
        name=organization.name,
        role=str(role),
        storage_user_id=organization.storage_user_id,
    )


def storage_user_id_for_organization(organization: ActiveOrganization, actor_user_id: str) -> str | None:
    """Return the storage principal, or the actor for a private org."""
    if organization.storage_user_id:
        return organization.storage_user_id
    if organization.id == private_organization_id(actor_user_id):
        return actor_user_id
    return None


async def private_organization_for_user(session: AsyncSession, user_id: str | None) -> str | None:
    if user_id is None:
        return None
    organization_id = private_organization_id(user_id)
    return await session.scalar(select(OrganizationRow.id).where(OrganizationRow.id == organization_id, OrganizationRow.status == "active"))


async def active_private_organization_for_user(session: AsyncSession, user_id: str | None) -> str | None:
    """Return the user's active private organization only with active membership."""
    active = await active_organization_for_user(session, user_id)
    return active.id if active is not None else None


def private_organization_for_user_sync(session: Session, user_id: str | None) -> str | None:
    if user_id is None:
        return None
    organization_id = private_organization_id(user_id)
    return session.scalar(select(OrganizationRow.id).where(OrganizationRow.id == organization_id, OrganizationRow.status == "active"))


def organization_from_owned_parent(parent: _OwnedRow | None, expected_user_id: str | None, *, parent_name: str) -> str | None:
    """Return a verified parent's organization, preserving NULL legacy quarantine."""
    if parent is None:
        return None
    if parent.user_id is None:
        if parent.organization_id is not None:
            raise ValueError(f"{parent_name} has organization ownership without an audit owner")
        return None
    if expected_user_id is not None and parent.user_id != expected_user_id:
        raise ValueError(f"{parent_name} belongs to a different user")
    expected_organization_id = private_organization_id(parent.user_id)
    if parent.organization_id is not None and parent.organization_id != expected_organization_id:
        raise ValueError(f"{parent_name} has conflicting organization ownership")
    return parent.organization_id


class OrganizationMismatchError(LookupError):
    """A write cannot be proven to belong to its organization; answer 404."""


def organization_for_write(active_organization_id: str | None, parent_organization_id: str | None, storage_user_id: str | None) -> str | None:
    """Return the organization to stamp on a new or re-parented row.

    Takes server-owned inputs only: the middleware-verified active organization
    (``resolve_organization_id()``), the organization of a parent row already
    loaded under the caller's user filter, and the storage principal of the
    workspace being written (``resolve_user_id(AUTO)``), which is not the row's
    ``user_id`` when the row is audited to a person, such as feedback in a shared
    workspace. Every organization is
    ``private_organization_id(storage principal)``, so any other value is a
    cross-organization attach or an actor/storage mix-up and raises
    :class:`OrganizationMismatchError`. With no active organization and no
    parent organization the result is ``None``, the quarantine marker, never a
    guess.
    """
    expected = private_organization_id(storage_user_id) if storage_user_id else None
    for organization_id in (active_organization_id, parent_organization_id):
        if organization_id is not None and organization_id != expected:
            raise OrganizationMismatchError("organization does not match the storage principal")
    return active_organization_id or parent_organization_id
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
