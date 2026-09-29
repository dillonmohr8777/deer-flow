"""SQLAlchemy-backed repository for the M4 entitlement gate.

Unlike ``BoardRepository``/``ClientRepository``, every method here takes
``organization_id`` explicitly rather than reading it from
``resolve_organization_id()``: the evaluator (``deerflow.authz.entitlements``)
is called with the *caller's* resolved organization already in hand, and an
admin/backfill path (§4 of the design) needs to write rows for organizations
other than the ambient request context.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.entitlements.model import OrganizationEntitlementRow


def _row_to_dict(row: OrganizationEntitlementRow) -> dict[str, Any]:
    return row.to_dict()


class EntitlementRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def get(self, organization_id: str, key: str) -> dict | None:
        async with self._sf() as session:
            row = await session.get(OrganizationEntitlementRow, (organization_id, key))
            return None if row is None else _row_to_dict(row)

    async def list_for_org(self, organization_id: str) -> list[dict]:
        stmt = select(OrganizationEntitlementRow).where(OrganizationEntitlementRow.organization_id == organization_id)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [_row_to_dict(r) for r in result.scalars()]

    async def upsert(
        self,
        organization_id: str,
        key: str,
        *,
        limit_value: int | None = None,
        source: str = "manual",
        status: str = "active",
    ) -> dict:
        """Set or replace one organization's entitlement row for ``key``.

        Admin/backfill write path (design §4). Not exposed on any route yet
        (design §7.3 leaves that to a follow-up); tests and a future
        operator script call this directly.
        """
        now = datetime.now(UTC)
        async with self._sf() as session:
            row = await session.get(OrganizationEntitlementRow, (organization_id, key))
            if row is None:
                row = OrganizationEntitlementRow(
                    organization_id=organization_id,
                    key=key,
                    limit_value=limit_value,
                    source=source,
                    status=status,
                    created_at=now,
                    updated_at=now,
                )
                session.add(row)
            else:
                row.limit_value = limit_value
                row.source = source
                row.status = status
                row.updated_at = now
            await session.commit()
            await session.refresh(row)
            return _row_to_dict(row)

    async def delete(self, organization_id: str, key: str) -> None:
        async with self._sf() as session:
            row = await session.get(OrganizationEntitlementRow, (organization_id, key))
            if row is not None:
                await session.delete(row)
                await session.commit()


__all__ = ["EntitlementRepository"]
