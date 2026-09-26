"""When a shared-workspace invitation still counts.

The invitation router (inspect/accept) and SSO provisioning
(``auto_create_requires_invitation``) both ask "is this invitation still
pending?", so the answer lives here once instead of in two copies that could
drift apart.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from deerflow.persistence.organizations.invitation import InvitationRow
from deerflow.persistence.organizations.model import OrganizationMemberRow, OrganizationRow

# Roles that may invite people into (and manage) a shared workspace.
SHARED_WORKSPACE_ADMIN_ROLES: tuple[str, ...] = ("owner", "admin")


def _as_utc(value: datetime) -> datetime:
    # SQLite hands back naive datetimes; every stored value is UTC.
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


async def active_shared_workspace_member(
    session: AsyncSession,
    organization_id: str,
    user_id: str,
) -> tuple[OrganizationRow | None, OrganizationMemberRow | None]:
    """Return ``(workspace, membership)`` for an active owner/admin.

    ``(None, None)`` when the organization is missing, inactive or private
    (no shared storage principal); ``(workspace, None)`` when ``user_id`` is
    not an active owner or admin of it.
    """
    organization = await session.scalar(
        select(OrganizationRow).where(
            OrganizationRow.id == organization_id,
            OrganizationRow.status == "active",
            OrganizationRow.storage_user_id.is_not(None),
        )
    )
    if organization is None:
        return None, None
    member = await session.scalar(
        select(OrganizationMemberRow).where(
            OrganizationMemberRow.organization_id == organization_id,
            OrganizationMemberRow.user_id == user_id,
            OrganizationMemberRow.status == "active",
            OrganizationMemberRow.role.in_(SHARED_WORKSPACE_ADMIN_ROLES),
        )
    )
    return organization, member


async def invitation_issuer_is_active(session: AsyncSession, invitation: InvitationRow) -> bool:
    """A pending token does not survive the removal or demotion of its issuer."""
    _organization, member = await active_shared_workspace_member(session, invitation.organization_id, invitation.created_by)
    return member is not None


async def has_pending_invitation(session: AsyncSession, email: str, *, now: datetime) -> bool:
    """Whether any invitation for ``email`` (case-insensitive) is still pending.

    Pending means: not consumed (accepted or revoked), not expired, for an
    active shared workspace whose issuer is still an active owner or admin
    there. This is the same bar ``/invitations/inspect`` and ``/accept`` hold
    a token to.
    """
    candidates = (
        await session.scalars(
            select(InvitationRow).where(
                func.lower(InvitationRow.email) == email.strip().lower(),
                InvitationRow.consumed_at.is_(None),
            )
        )
    ).all()
    for invitation in candidates:
        if _as_utc(invitation.expires_at) <= now:
            continue
        if await invitation_issuer_is_active(session, invitation):
            return True
    return False


__all__ = [
    "SHARED_WORKSPACE_ADMIN_ROLES",
    "active_shared_workspace_member",
    "has_pending_invitation",
    "invitation_issuer_is_active",
]
