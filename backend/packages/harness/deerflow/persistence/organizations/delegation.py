"""Server-created authority for an internal subject to act for one member.

Contract section 4: an internal token plus an owner header is never enough by
itself. A delegation ties one internal subject (a scheduled task, a channel
connection, ...) to one owner in one organization for a narrowed set of route
permissions. Everything denies by default: a missing, revoked, expired,
out-of-scope or ambiguous delegation, or one whose owner no longer holds an
active membership in an active organization, resolves to ``None``.

Workspace storage principals are never members, so they can never own a
delegation: ``grant`` refuses them and resolution would deny them.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.organizations.model import OrganizationDelegationRow
from deerflow.persistence.organizations.resolution import ActiveOrganization, active_organization_for_user


@dataclass(frozen=True, slots=True)
class ActiveDelegation:
    """A delegation that passed every check, with its owner's validated membership."""

    id: str
    organization: ActiveOrganization
    subject_type: str
    subject_id: str
    owner_user_id: str
    scopes: frozenset[str]


def _is_expired(expires_at: datetime | None) -> bool:
    if expires_at is None:
        return False
    if expires_at.tzinfo is None:
        # SQLite drops tzinfo on read; stored values are UTC.
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at <= datetime.now(UTC)


def _active_predicates(organization_id: str | None, subject_type: str, subject_id: str):
    predicates = [
        OrganizationDelegationRow.subject_type == subject_type,
        OrganizationDelegationRow.subject_id == subject_id,
        OrganizationDelegationRow.status == "active",
    ]
    if organization_id is not None:
        predicates.append(OrganizationDelegationRow.organization_id == organization_id)
    return predicates


class OrganizationDelegationRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def grant(
        self,
        *,
        organization_id: str,
        subject_type: str,
        subject_id: str,
        owner_user_id: str,
        scopes: Sequence[str],
        expires_at: datetime | None = None,
    ) -> str:
        """Create the subject's active delegation and return its id.

        The owner must hold an active membership in the organization now, so a
        delegation can never lie dormant until someone joins. A new grant
        revokes the subject's previous active delegation in that organization.
        """
        if not (organization_id and subject_type and subject_id and owner_user_id):
            raise ValueError("a delegation needs an organization, a subject and an owner")
        if isinstance(scopes, str) or not scopes or not all(isinstance(scope, str) and scope for scope in scopes):
            raise ValueError("a delegation needs a list of non-empty permission scopes")
        delegation_id = str(uuid.uuid4())
        async with self._sf() as session, session.begin():
            if await active_organization_for_user(session, owner_user_id, organization_id) is None:
                raise PermissionError("the delegation owner has no active membership in the organization")
            await session.execute(update(OrganizationDelegationRow).where(*_active_predicates(organization_id, subject_type, subject_id)).values(status="revoked", updated_at=datetime.now(UTC)))
            session.add(
                OrganizationDelegationRow(
                    id=delegation_id,
                    organization_id=organization_id,
                    subject_type=subject_type,
                    subject_id=subject_id,
                    owner_user_id=owner_user_id,
                    scopes=sorted(set(scopes)),
                    status="active",
                    expires_at=expires_at,
                )
            )
        return delegation_id

    async def revoke(self, *, subject_type: str, subject_id: str) -> int:
        """Revoke the subject's active delegations in every organization; return how many."""
        async with self._sf() as session, session.begin():
            result = await session.execute(update(OrganizationDelegationRow).where(*_active_predicates(None, subject_type, subject_id)).values(status="revoked", updated_at=datetime.now(UTC)))
            return result.rowcount

    async def resolve_active_delegation(self, *, subject_type: str, subject_id: str, organization_id: str, scope: str) -> ActiveDelegation | None:
        """Return the subject's delegation when every check passes, else ``None``.

        Everything is re-read on each call, so revoking the delegation or the
        owner's membership, or suspending the organization, denies the next
        request: status, expiry, the requested scope, and the owner's active
        membership in an active organization.
        """
        if not (subject_type and subject_id and organization_id and scope):
            return None
        async with self._sf() as session:
            rows = (await session.execute(select(OrganizationDelegationRow).where(*_active_predicates(organization_id, subject_type, subject_id)).limit(2))).scalars().all()
            # ponytail: nothing but grant() enforces one active delegation per
            # subject (M3 adds no DDL), so a concurrent-grant race can leave two.
            # Deny rather than pick an owner; add a partial unique index with 0033.
            if len(rows) != 1:
                return None
            row = rows[0]
            scopes = frozenset(item for item in row.scopes if isinstance(item, str)) if isinstance(row.scopes, list) else frozenset()
            if _is_expired(row.expires_at) or scope not in scopes:
                return None
            organization = await active_organization_for_user(session, row.owner_user_id, organization_id)
        if organization is None:
            return None
        return ActiveDelegation(
            id=row.id,
            organization=organization,
            subject_type=row.subject_type,
            subject_id=row.subject_id,
            owner_user_id=row.owner_user_id,
            scopes=scopes,
        )

    async def is_membership_active(self, *, user_id: str | None, organization_id: str | None) -> bool:
        """Cheap re-check for open streams: an active member of an active organization.

        A missing organization is ``False``, never the caller's private one.
        """
        if not user_id or not organization_id:
            return False
        async with self._sf() as session:
            return await active_organization_for_user(session, user_id, organization_id) is not None
