"""Shared dedicated-customer binding and recipient checks; no router imports."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select

from app.gateway.client_boundary import CLIENT_ROLE
from deerflow.persistence.clients.model import ClientAssignmentRow, ClientRow
from deerflow.persistence.organizations.invitation_policy import active_shared_workspace_member
from deerflow.persistence.organizations.model import OrganizationMemberRow, OrganizationRow
from deerflow.persistence.user.model import UserRow

PLAIN_USER_ROLE = "user"


async def validate_customer_workspace(session, *, organization, actor_id, canonical=None):
    """Issuance and redemption require the same isolated binding and issuer authority."""
    canonical = canonical or await session.get(ClientRow, organization.customer_client_id)
    if canonical is None or canonical.status != "active":
        raise HTTPException(409, "Customer workspace binding is unavailable")
    agency, agency_member = await active_shared_workspace_member(session, canonical.organization_id, actor_id)
    target, target_member = await active_shared_workspace_member(session, organization.id, actor_id)
    issuer = await session.get(UserRow, actor_id, populate_existing=True)
    bindings = (await session.scalars(select(OrganizationRow.id).where(OrganizationRow.customer_client_id == canonical.id))).all()
    own_roster = await session.scalar(select(ClientRow.id).where(ClientRow.organization_id == organization.id).limit(1))
    if (
        agency is None
        or agency_member is None
        or agency.customer_client_id is not None
        or target is None
        or target_member is None
        or target.id == agency.id
        or target.storage_user_id == agency.storage_user_id
        or bindings != [organization.id]
        or own_roster is not None
        or issuer is None
        or issuer.disabled_at is not None
        or issuer.system_role != "admin"
    ):
        raise HTTPException(409, "Customer workspace binding is unavailable")
    return canonical


async def fresh_customer_assignments(session, user, *, target_id=None, client_id=None):
    """Only a plain/client account with no other shared scope may become a contact."""
    if user is None or user.disabled_at is not None or (user.system_role != PLAIN_USER_ROLE and user.system_role != CLIENT_ROLE):
        raise HTTPException(409, "Choose an active plain or client account for a dedicated customer workspace")
    assignments = (await session.scalars(select(ClientAssignmentRow).where(ClientAssignmentRow.user_id == user.id))).all()
    shared = (
        await session.scalars(
            select(OrganizationMemberRow.organization_id)
            .join(OrganizationRow, OrganizationRow.id == OrganizationMemberRow.organization_id)
            .where(OrganizationMemberRow.user_id == user.id, OrganizationMemberRow.status == "active", OrganizationRow.storage_user_id.is_not(None))
        )
    ).all()
    if any(a.client_id != client_id or a.organization_id != target_id for a in assignments) or any(workspace != target_id for workspace in shared):
        raise HTTPException(409, "Client account is already assigned; review its existing workspace")
    return assignments
