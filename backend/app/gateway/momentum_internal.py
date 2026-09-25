"""The one gate for Momentum-internal surfaces (team channels, AI Academy).

Two conditions, both required:

1. ``config.private_workspace.enabled`` -- this is Momentum's own instance,
   the same boundary the Desk and the Board use. Client-facing MomoBots
   leave it false, so none of this exists there.
2. The caller's role in the active organization is a staff role. ``owner``,
   ``admin`` and ``member`` are staff; anything else (a future ``client``
   role, a missing membership, a PAT with no organization role) is not.

Failing either condition answers 404, never 403, so a client can't even
learn these routes exist.
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from app.gateway.deps import get_current_user_from_request

STAFF_ROLES: frozenset[str] = frozenset({"owner", "admin", "member"})
ADMIN_ROLES: frozenset[str] = frozenset({"owner", "admin"})


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Not found")


def is_momentum_staff(request: Request, config) -> bool:
    """Whether the caller may see Momentum-internal surfaces. Fails closed."""
    private_workspace = getattr(config, "private_workspace", None)
    if getattr(private_workspace, "enabled", False) is not True:
        return False
    if getattr(request.state, "organization_id", None) is None:
        return False
    return getattr(request.state, "organization_role", None) in STAFF_ROLES


async def require_momentum_staff(request: Request, config) -> tuple[str, str, str]:
    """Return ``(organization_id, user_id, role)`` for a staff caller, else 404."""
    if not is_momentum_staff(request, config):
        raise _not_found()
    user = await get_current_user_from_request(request)
    return str(request.state.organization_id), str(user.id), str(request.state.organization_role)
