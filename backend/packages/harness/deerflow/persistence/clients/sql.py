"""SQLAlchemy-backed client roster repository (Momentum Phase 2 item 2).

``clients`` is organization-owned (no ``user_id``): every read/write is
scoped by ``resolve_organization_id()`` beside the M3 helpers, exactly like
the other organization-scoped tables (`AGENTS.md` "Organization isolation
(M3)"). A foreign or missing client is indistinguishable -- callers map both
to ``None``/``False`` and routers answer 404.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.clients.model import ClientAssignmentRow, ClientRow
from deerflow.persistence.organizations.resolution import OrganizationMismatchError, organization_for_write
from deerflow.persistence.projects.model import ProjectRow
from deerflow.runtime.user_context import AUTO, get_workspace_actor_user_id, resolve_organization_id, resolve_user_id
from deerflow.utils.time import coerce_iso

ClientStatus = Literal["active", "inactive", "prospect"]
AssignmentRole = Literal["account_manager", "contributor", "client_contact"]
UpsertOutcome = Literal["created", "updated", "skipped"]


def _row_to_dict(row: ClientRow) -> dict[str, Any]:
    d = row.to_dict()
    for key in ("created_at", "updated_at"):
        val = d.get(key)
        if isinstance(val, datetime):
            d[key] = coerce_iso(val)
    return d


def _assignment_to_dict(row: ClientAssignmentRow) -> dict[str, Any]:
    d = row.to_dict()
    for key in ("created_at", "updated_at"):
        val = d.get(key)
        if isinstance(val, datetime):
            d[key] = coerce_iso(val)
    return d


class ClientRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @staticmethod
    def _scope(stmt: Any, organization_id: str | None) -> Any:
        if organization_id is not None:
            return stmt.where(ClientRow.organization_id == organization_id)
        return stmt

    async def create(
        self,
        *,
        display_name: str,
        aliases: list[str] | None = None,
        status: ClientStatus = "active",
        email_domains: list[str] | None = None,
        slack_channel_ids: list[str] | None = None,
        registry_id: str | None = None,
        notes: str = "",
    ) -> dict:
        now = datetime.now(UTC)
        row = ClientRow(
            id=uuid.uuid4().hex,
            display_name=display_name,
            aliases=aliases or [],
            status=status,
            email_domains=email_domains or [],
            slack_channel_ids=slack_channel_ids or [],
            registry_id=registry_id,
            notes=notes,
            created_at=now,
            updated_at=now,
        )
        row.organization_id = organization_for_write(resolve_organization_id(), None, resolve_user_id(AUTO, method_name="ClientRepository.create"))
        async with self._sf() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return _row_to_dict(row)

    async def get(self, client_id: str) -> dict | None:
        organization_id = resolve_organization_id()
        async with self._sf() as session:
            row = await session.get(ClientRow, client_id)
            if row is None or (organization_id is not None and row.organization_id != organization_id):
                return None
            return _row_to_dict(row)

    async def list(self, *, status: ClientStatus | None = None) -> list[dict]:
        organization_id = resolve_organization_id()
        stmt = self._scope(select(ClientRow), organization_id).order_by(ClientRow.display_name.asc(), ClientRow.id.asc())
        if status is not None:
            stmt = stmt.where(ClientRow.status == status)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [_row_to_dict(r) for r in result.scalars()]

    async def list_mine(self) -> list[dict]:
        """Clients the acting (authenticated) user is assigned to, org scoped."""
        actor_user_id = get_workspace_actor_user_id()
        if actor_user_id is None:
            return []
        organization_id = resolve_organization_id()
        stmt = select(ClientRow).join(ClientAssignmentRow, ClientAssignmentRow.client_id == ClientRow.id).where(ClientAssignmentRow.user_id == actor_user_id)
        stmt = self._scope(stmt, organization_id).order_by(ClientRow.display_name.asc(), ClientRow.id.asc())
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [_row_to_dict(r) for r in result.scalars()]

    async def patch(
        self,
        client_id: str,
        *,
        display_name: str | None = None,
        aliases: list[str] | None = None,
        status: ClientStatus | None = None,
        email_domains: list[str] | None = None,
        slack_channel_ids: list[str] | None = None,
        notes: str | None = None,
    ) -> dict | None:
        organization_id = resolve_organization_id()
        async with self._sf() as session:
            row = await session.get(ClientRow, client_id)
            if row is None or (organization_id is not None and row.organization_id != organization_id):
                return None
            if display_name is not None:
                row.display_name = display_name
            if aliases is not None:
                row.aliases = aliases
            if status is not None:
                row.status = status
            if email_domains is not None:
                row.email_domains = email_domains
            if slack_channel_ids is not None:
                row.slack_channel_ids = slack_channel_ids
            if notes is not None:
                row.notes = notes
            await session.commit()
            await session.refresh(row)
            return _row_to_dict(row)

    async def set_status(self, client_id: str, status: ClientStatus) -> dict | None:
        return await self.patch(client_id, status=status)

    async def project_counts(self, client_ids: list[str]) -> dict[str, int]:
        """Linked-project counts, keyed by client id (Client Spaces view)."""
        if not client_ids:
            return {}
        stmt = select(ProjectRow.client_id, func.count()).where(ProjectRow.client_id.in_(client_ids)).group_by(ProjectRow.client_id)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return {client_id: count for client_id, count in result.all() if client_id is not None}

    async def list_assignments(self, client_id: str) -> list[dict] | None:
        """Assignment rows for one client, or ``None`` for a missing/foreign client."""
        if await self.get(client_id) is None:
            return None
        stmt = select(ClientAssignmentRow).where(ClientAssignmentRow.client_id == client_id).order_by(ClientAssignmentRow.user_id.asc())
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [_assignment_to_dict(r) for r in result.scalars()]

    async def assignments_by_client(self, client_ids: list[str]) -> dict[str, list[dict]]:
        """Batched sibling of :meth:`list_assignments` for list responses (no N+1)."""
        if not client_ids:
            return {}
        stmt = select(ClientAssignmentRow).where(ClientAssignmentRow.client_id.in_(client_ids)).order_by(ClientAssignmentRow.client_id.asc(), ClientAssignmentRow.user_id.asc())
        by_client: dict[str, list[dict]] = {client_id: [] for client_id in client_ids}
        async with self._sf() as session:
            result = await session.execute(stmt)
            for row in result.scalars():
                by_client.setdefault(row.client_id, []).append(_assignment_to_dict(row))
        return by_client

    async def add_assignment(self, client_id: str, user_id: str, role: AssignmentRole) -> dict | None:
        """Upsert one ``(client_id, user_id)`` assignment; ``None`` for a missing/foreign client."""
        organization_id = resolve_organization_id()
        async with self._sf() as session:
            client = await session.get(ClientRow, client_id)
            if client is None or (organization_id is not None and client.organization_id != organization_id):
                return None
            now = datetime.now(UTC)
            existing = await session.get(ClientAssignmentRow, (client_id, user_id))
            if existing is not None:
                existing.role = role
                existing.updated_at = now
                await session.commit()
                await session.refresh(existing)
                return _assignment_to_dict(existing)
            row = ClientAssignmentRow(
                client_id=client_id,
                user_id=user_id,
                organization_id=client.organization_id,
                role=role,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return _assignment_to_dict(row)

    async def remove_assignment(self, client_id: str, user_id: str) -> bool:
        organization_id = resolve_organization_id()
        stmt = sa_delete(ClientAssignmentRow).where(ClientAssignmentRow.client_id == client_id, ClientAssignmentRow.user_id == user_id)
        if organization_id is not None:
            stmt = stmt.where(ClientAssignmentRow.organization_id == organization_id)
        async with self._sf() as session:
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount > 0

    async def upsert_by_registry_id(
        self,
        *,
        registry_id: str,
        display_name: str,
        aliases: list[str] | None = None,
        status: ClientStatus = "active",
        email_domains: list[str] | None = None,
        slack_channel_ids: list[str] | None = None,
        notes: str = "",
    ) -> tuple[UpsertOutcome, dict | None]:
        """Upsert one registry entry by ``registry_id`` within the active organization.

        Never deletes. A ``registry_id`` already used by a *different*
        organization cannot collide: the unique constraint is
        ``(organization_id, registry_id)``, so each organization keeps its own
        namespace.
        """
        organization_id = resolve_organization_id()
        async with self._sf() as session:
            stmt = select(ClientRow).where(ClientRow.registry_id == registry_id)
            stmt = self._scope(stmt, organization_id)
            existing = (await session.execute(stmt)).scalars().first()
            now = datetime.now(UTC)
            if existing is not None:
                existing.display_name = display_name
                existing.aliases = aliases or []
                existing.status = status
                existing.email_domains = email_domains or []
                existing.slack_channel_ids = slack_channel_ids or []
                existing.notes = notes
                existing.updated_at = now
                await session.commit()
                await session.refresh(existing)
                return "updated", _row_to_dict(existing)
            row = ClientRow(
                id=uuid.uuid4().hex,
                display_name=display_name,
                aliases=aliases or [],
                status=status,
                email_domains=email_domains or [],
                slack_channel_ids=slack_channel_ids or [],
                registry_id=registry_id,
                notes=notes,
                created_at=now,
                updated_at=now,
            )
            try:
                row.organization_id = organization_for_write(organization_id, None, resolve_user_id(AUTO, method_name="ClientRepository.upsert_by_registry_id"))
            except OrganizationMismatchError:
                return "skipped", None
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return "created", _row_to_dict(row)
