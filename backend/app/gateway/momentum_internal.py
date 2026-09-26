"""The one gate for Momentum-internal surfaces (team channels, AI Academy).

Three conditions, all required:

1. ``config.momentum_internal.enabled`` is true. Off by default, so an
   instance that never mentions it shows none of this.
2. The caller's active workspace (organization) has a slug listed in
   ``config.momentum_internal.organization_slugs``. That list names the
   agency's own workspace; client workspaces on the same instance never
   belong in it, so a client never sees these surfaces even as the owner of
   their own workspace.
3. The caller is staff in that workspace: role ``owner``, ``admin`` or
   ``member``, **and** no ``client_contact`` client assignment there. Client
   people live in the agency workspace as ordinary members whose only
   distinguishing mark is that assignment (the Board confines them by it),
   so the role alone can't tell staff from clients. A ``client`` membership
   role (an invitation can grant it) is never staff, which also covers the
   gap between a client accepting an invite and being assigned.

Failing any condition answers 404, never 403. The routers run this as a
dependency, ahead of their permission check, and stay out of the OpenAPI
schema, so nobody outside can learn the routes exist.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select

from app.gateway.deps import get_config, get_current_user_from_request
from deerflow.config.app_config import AppConfig
from deerflow.persistence.clients.model import ClientAssignmentRow
from deerflow.persistence.organizations.model import OrganizationRow

STAFF_ROLES: frozenset[str] = frozenset({"owner", "admin", "member"})
ADMIN_ROLES: frozenset[str] = frozenset({"owner", "admin"})
# Client assignment roles that mark a person as the client, not staff
# (``routers/clients.py`` AssignmentRole: account_manager and contributor
# are staff assignments).
CLIENT_ASSIGNMENT_ROLES: frozenset[str] = frozenset({"client_contact"})


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Not found")


def _configured_slugs(config) -> frozenset[str]:
    settings = getattr(config, "momentum_internal", None)
    if getattr(settings, "enabled", False) is not True:
        return frozenset()
    slugs = getattr(settings, "organization_slugs", None) or []
    return frozenset(s.strip().lower() for s in slugs if isinstance(s, str) and s.strip())


async def _organization_slug(organization_id: str) -> str | None:
    """The active organization's slug, or ``None`` when missing or inactive."""
    # Lazy import so a test's monkeypatched session factory takes effect,
    # matching ``board.py``'s ``_is_active_org_admin``.
    from deerflow.persistence.engine import get_session_factory

    session_factory = get_session_factory()
    if session_factory is None:
        return None
    stmt = select(OrganizationRow.slug).where(OrganizationRow.id == organization_id, OrganizationRow.status == "active")
    async with session_factory() as session:
        slug = (await session.execute(stmt)).scalars().first()
    return slug.lower() if isinstance(slug, str) else None


async def _is_client_contact(organization_id: str, user_id: str) -> bool:
    """Whether *user_id* holds a client-side assignment in the organization. Fails closed."""
    from deerflow.persistence.engine import get_session_factory

    session_factory = get_session_factory()
    if session_factory is None:
        return True
    stmt = select(ClientAssignmentRow.user_id).where(
        ClientAssignmentRow.organization_id == organization_id,
        ClientAssignmentRow.user_id == user_id,
        ClientAssignmentRow.role.in_(sorted(CLIENT_ASSIGNMENT_ROLES)),
    )
    async with session_factory() as session:
        return (await session.execute(stmt)).scalars().first() is not None


def _caller_id(request: Request) -> str | None:
    actor = getattr(request.state, "actor_user_id", None)
    if actor:
        return str(actor)
    user = getattr(request.state, "user", None)
    return str(user.id) if getattr(user, "id", None) else None


async def is_momentum_staff(request: Request, config) -> bool:
    """Whether the caller may see Momentum-internal surfaces. Fails closed."""
    slugs = _configured_slugs(config)
    if not slugs:
        return False
    organization_id = getattr(request.state, "organization_id", None)
    if organization_id is None:
        return False
    if getattr(request.state, "organization_role", None) not in STAFF_ROLES:
        return False
    user_id = _caller_id(request)
    if user_id is None:
        return False
    if await _organization_slug(str(organization_id)) not in slugs:
        return False
    return not await _is_client_contact(str(organization_id), user_id)


async def require_momentum_staff(request: Request, config) -> tuple[str, str, str]:
    """Return ``(organization_id, user_id, role)`` for a staff caller, else 404."""
    if not await is_momentum_staff(request, config):
        raise _not_found()
    user = await get_current_user_from_request(request)
    return str(request.state.organization_id), str(user.id), str(request.state.organization_role)


async def momentum_staff_only(request: Request, config: AppConfig = Depends(get_config)) -> None:
    """Router-level dependency: 404 before any permission check can answer 403."""
    if not await is_momentum_staff(request, config):
        raise _not_found()
