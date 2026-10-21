"""Client chat requires a dedicated customer workspace, not agency memory."""

from fastapi import HTTPException
from sqlalchemy import func, select

from deerflow.persistence.clients.model import ClientAssignmentRow, ClientRow
from deerflow.persistence.organizations.model import OrganizationRow
from deerflow.runtime.user_context import resolve_organization_id


async def is_client_contact(user) -> bool:
    if getattr(user, "system_role", None) == "client":
        return True
    from deerflow.persistence.engine import get_session_factory

    factory = get_session_factory()
    org = resolve_organization_id()
    if factory is None or not org:
        return False
    async with factory() as session:
        return (
            await session.scalar(
                select(ClientAssignmentRow.client_id)
                .where(
                    ClientAssignmentRow.organization_id == org,
                    ClientAssignmentRow.user_id == str(user.id),
                    ClientAssignmentRow.role == "client_contact",
                )
                .limit(1)
            )
            is not None
        )


async def require_client_workspace(user) -> None:
    """Never run a customer's Max against multi-client company summaries."""
    if not await is_client_contact(user):
        return
    if getattr(user, "system_role", None) != "client":
        raise HTTPException(403, "Your team must finish setting up your client account before Momo chat is available")
    from deerflow.persistence.engine import get_session_factory

    factory = get_session_factory()
    org = resolve_organization_id()
    if factory is None or not org:
        raise HTTPException(403, "A dedicated customer workspace is required")
    async with factory() as session:
        binding = await session.scalar(select(OrganizationRow.customer_client_id).where(OrganizationRow.id == org, OrganizationRow.status == "active"))
        total = await session.scalar(select(func.count()).select_from(ClientRow).where(ClientRow.organization_id == org))
        mine = await session.scalar(
            select(ClientRow.id)
            .join(ClientAssignmentRow, ClientAssignmentRow.client_id == ClientRow.id)
            .where(
                ClientRow.id == binding,
                ClientRow.organization_id != org,
                ClientRow.status == "active",
                ClientAssignmentRow.organization_id == org,
                ClientAssignmentRow.user_id == str(user.id),
                ClientAssignmentRow.role == "client_contact",
            )
        )
    if total != 0 or mine is None or binding != mine:
        raise HTTPException(403, "Your team must set up a dedicated customer workspace before Momo chat is available")
