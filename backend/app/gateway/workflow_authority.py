"""Re-check the original actor's organization and permissions before paid work."""

from app.gateway.authz import resolve_route_permissions
from app.gateway.routers.auth import get_local_provider
from deerflow.persistence.engine import get_session_factory
from deerflow.persistence.organizations.resolution import active_organization_for_user, storage_user_id_for_organization


async def workflow_actor_authorized(actor: str, organization: str | None, storage_user: str) -> bool:
    if not actor or not organization or not storage_user:
        return False
    factory = get_session_factory()
    if factory is None:
        return False
    async with factory() as session:
        active = await active_organization_for_user(session, actor, organization)
    if active is None or storage_user_id_for_organization(active, actor) != storage_user:
        return False
    user = await get_local_provider().get_user(actor)
    if user is None:
        return False
    permissions = await resolve_route_permissions(user, is_internal=False)
    return "runs:create" in permissions
