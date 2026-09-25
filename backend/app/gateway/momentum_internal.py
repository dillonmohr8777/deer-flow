"""The one gate for Momentum-internal surfaces (team channels, AI Academy).

Three conditions, all required:

1. ``config.momentum_internal.enabled`` is true. Off by default, so an
   instance that never mentions it shows none of this.
2. The caller's active workspace (organization) has a slug listed in
   ``config.momentum_internal.organization_slugs``. That list names the
   agency's own workspace; client workspaces on the same instance never
   belong in it, so a client never sees these surfaces even as the owner of
   their own workspace.
3. The caller's role in that workspace is a staff role. ``owner``, ``admin``
   and ``member`` are staff; anything else (a future ``client`` role, a
   missing membership, a PAT with no organization role) is not.

Failing any condition answers 404, never 403, so nobody outside can even
learn these routes exist.
"""

from __future__ import annotations

from fastapi import HTTPException, Request
from sqlalchemy import select

from app.gateway.deps import get_current_user_from_request
from deerflow.persistence.organizations.model import OrganizationRow

STAFF_ROLES: frozenset[str] = frozenset({"owner", "admin", "member"})
ADMIN_ROLES: frozenset[str] = frozenset({"owner", "admin"})


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
    return await _organization_slug(str(organization_id)) in slugs


async def require_momentum_staff(request: Request, config) -> tuple[str, str, str]:
    """Return ``(organization_id, user_id, role)`` for a staff caller, else 404."""
    if not await is_momentum_staff(request, config):
        raise _not_found()
    user = await get_current_user_from_request(request)
    return str(request.state.organization_id), str(user.id), str(request.state.organization_role)
