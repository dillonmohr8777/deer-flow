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
