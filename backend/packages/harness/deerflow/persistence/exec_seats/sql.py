"""SQLAlchemy-backed agent-seat repository (queue item e9, exec-seats).

Organization-scoped exactly like ``BoardRepository``/``TeamBoardRepository``:
every read/write is scoped by ``resolve_organization_id()``, and a foreign or
missing seat comes back as ``None`` so a caller can answer 404. Whether a
transition is actually allowed is ``deerflow.exec_seats.workflow``'s job, not
this repository's -- it only enforces the organization boundary and persists
whatever status a caller (already checked against the workflow) asks for.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.exec_seats.model import AgentSeatRow, AgentSeatStatus
from deerflow.persistence.organizations.resolution import organization_for_write
from deerflow.runtime.user_context import AUTO, resolve_organization_id, resolve_user_id
from deerflow.utils.time import coerce_iso


def _to_dict(row: AgentSeatRow) -> dict[str, Any]:
    d = row.to_dict()
    for key in ("created_at", "updated_at"):
        val = d.get(key)
        if isinstance(val, datetime):
            d[key] = coerce_iso(val)
    return d


class AgentSeatRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @staticmethod
    def _scope(stmt: Any, organization_id: str | None) -> Any:
        if organization_id is not None:
            return stmt.where(AgentSeatRow.organization_id == organization_id)
        return stmt

    async def claim_seat(
        self,
        *,
        seat: str,
        agent_name: str,
        scope: str = "",
        kpi: str = "",
        weekly_token_budget: int = 0,
        claimed_by_user_id: str | None = None,
    ) -> dict:
        """Create a new claim. Does not check for an existing claim on *seat*
        (EXECUTIVE.md's "Confirm" step is where overlap gets caught; a
        contested seat can have more than one open claim at once)."""
        now = datetime.now(UTC)
        row = AgentSeatRow(
            id=uuid.uuid4().hex,
            organization_id=organization_for_write(resolve_organization_id(), None, resolve_user_id(AUTO, method_name="AgentSeatRepository.claim_seat")),
            seat=seat,
            agent_name=agent_name,
            scope=scope,
            kpi=kpi,
            weekly_token_budget=weekly_token_budget,
            status=AgentSeatStatus.CLAIMED,
            claimed_by_user_id=claimed_by_user_id,
            created_at=now,
            updated_at=now,
        )
        async with self._sf() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return _to_dict(row)

    async def get_seat(self, seat_id: str) -> dict | None:
        organization_id = resolve_organization_id()
        async with self._sf() as session:
            row = await session.get(AgentSeatRow, seat_id)
            if row is None or (organization_id is not None and row.organization_id != organization_id):
                return None
            return _to_dict(row)

    async def list_seats(self, *, status: str | None = None) -> list[dict]:
        """List seats in the active organization."""
        organization_id = resolve_organization_id()
        stmt = self._scope(select(AgentSeatRow), organization_id)
        if status is not None:
            stmt = stmt.where(AgentSeatRow.status == status)
        stmt = stmt.order_by(AgentSeatRow.created_at.asc(), AgentSeatRow.id.asc())
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [_to_dict(r) for r in result.scalars()]

    async def ratified_holder(self, seat: str) -> dict | None:
        """The currently ratified claim for *seat* in the active organization, if any."""
        organization_id = resolve_organization_id()
        stmt = self._scope(select(AgentSeatRow), organization_id).where(AgentSeatRow.seat == seat, AgentSeatRow.status == AgentSeatStatus.RATIFIED)
        stmt = stmt.order_by(AgentSeatRow.updated_at.desc()).limit(1)
        async with self._sf() as session:
            result = await session.execute(stmt)
            row = result.scalars().first()
            return _to_dict(row) if row is not None else None

    async def patch_seat(self, seat_id: str, *, status: str | None = None, ratified_by_user_id: str | None = None) -> dict | None:
        """Persist a status transition; ``None`` for a missing/foreign seat.

        Callers check ``deerflow.exec_seats.workflow.assert_can_*`` before
        calling this -- it never re-derives authorization itself.
        """
        organization_id = resolve_organization_id()
        async with self._sf() as session:
            row = await session.get(AgentSeatRow, seat_id)
            if row is None or (organization_id is not None and row.organization_id != organization_id):
                return None
            if status is not None:
                row.status = status
            if ratified_by_user_id is not None:
                row.ratified_by_user_id = ratified_by_user_id
            await session.commit()
            await session.refresh(row)
            return _to_dict(row)
