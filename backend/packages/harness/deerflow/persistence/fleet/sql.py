"""SQLAlchemy-backed repository for fleet template-to-client agent bindings.

``fleet_agent_bindings`` is organization-owned (no per-row ``user_id`` filter,
only ``organization_id``), the same scoping shape as ``ClientRepository``
(`AGENTS.md` "Organization isolation (M3)"): every read/write is scoped by
``resolve_organization_id()`` / ``organization_for_write()``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.fleet.model import FleetAgentBindingRow
from deerflow.persistence.organizations.resolution import organization_for_write
from deerflow.runtime.user_context import AUTO, resolve_organization_id, resolve_user_id
from deerflow.utils.time import coerce_iso


class FleetBindingExistsError(Exception):
    """Raised by :meth:`FleetBindingRepository.create` on a duplicate ``(client_id, template_id)``."""


def _row_to_dict(row: FleetAgentBindingRow) -> dict[str, Any]:
    d = row.to_dict()
    for key in ("created_at", "updated_at"):
        val = d.get(key)
        if isinstance(val, datetime):
            d[key] = coerce_iso(val)
    return d


class FleetBindingRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @staticmethod
    def _scope(stmt: Any, organization_id: str | None) -> Any:
        if organization_id is not None:
            return stmt.where(FleetAgentBindingRow.organization_id == organization_id)
        return stmt

    async def create(
        self,
        *,
        client_id: str,
        template_id: str,
        template_version: str,
        agent_name: str,
        agent_owner_user_id: str,
        scheduled_task_id: str | None = None,
    ) -> dict:
        now = datetime.now(UTC)
        row = FleetAgentBindingRow(
            id=uuid.uuid4().hex,
            client_id=client_id,
            template_id=template_id,
            template_version=template_version,
            agent_name=agent_name,
            agent_owner_user_id=agent_owner_user_id,
            scheduled_task_id=scheduled_task_id,
            created_at=now,
            updated_at=now,
        )
        row.organization_id = organization_for_write(resolve_organization_id(), None, resolve_user_id(AUTO, method_name="FleetBindingRepository.create"))
        try:
            async with self._sf() as session:
                session.add(row)
                await session.commit()
                await session.refresh(row)
                return _row_to_dict(row)
        except IntegrityError as e:
            raise FleetBindingExistsError(f"Client {client_id!r} already has an agent stamped from template {template_id!r}") from e

    async def get_by_client_and_template(self, client_id: str, template_id: str) -> dict | None:
        organization_id = resolve_organization_id()
        stmt = self._scope(
            select(FleetAgentBindingRow).where(FleetAgentBindingRow.client_id == client_id, FleetAgentBindingRow.template_id == template_id),
            organization_id,
        )
        async with self._sf() as session:
            row = (await session.execute(stmt)).scalars().first()
            return _row_to_dict(row) if row is not None else None

    async def list_by_client(self, client_id: str) -> list[dict]:
        organization_id = resolve_organization_id()
        stmt = self._scope(select(FleetAgentBindingRow).where(FleetAgentBindingRow.client_id == client_id), organization_id)
        stmt = stmt.order_by(FleetAgentBindingRow.created_at.asc())
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [_row_to_dict(r) for r in result.scalars()]
