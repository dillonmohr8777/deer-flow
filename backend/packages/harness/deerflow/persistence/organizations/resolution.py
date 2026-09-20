"""Small server-side organization resolution helpers for the dual-write window."""

from __future__ import annotations

from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from deerflow.persistence.organizations.identity import private_organization_id
from deerflow.persistence.organizations.model import OrganizationMemberRow, OrganizationRow


class _OwnedRow(Protocol):
    user_id: str | None
    organization_id: str | None


async def private_organization_for_user(session: AsyncSession, user_id: str | None) -> str | None:
    if user_id is None:
        return None
    organization_id = private_organization_id(user_id)
    return await session.scalar(select(OrganizationRow.id).where(OrganizationRow.id == organization_id, OrganizationRow.status == "active"))


async def active_private_organization_for_user(session: AsyncSession, user_id: str | None) -> str | None:
    """Return the user's active private organization only with active membership."""
    if user_id is None:
        return None
    organization_id = private_organization_id(user_id)
    return await session.scalar(
        select(OrganizationRow.id)
        .join(
            OrganizationMemberRow,
            (OrganizationMemberRow.organization_id == OrganizationRow.id) & (OrganizationMemberRow.user_id == user_id),
        )
        .where(
            OrganizationRow.id == organization_id,
            OrganizationRow.status == "active",
            OrganizationMemberRow.status == "active",
        )
    )


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
