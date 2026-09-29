"""SQLAlchemy-backed repository for Momentum agent hires (queue item e12, hiring).

Organization-scoped exactly like ``AgentSeatRepository``: every read/write is
scoped by ``resolve_organization_id()``, and a foreign or missing hire comes
back as ``None`` so a caller can answer accordingly. Whether a hire or a
retire is actually allowed is ``deerflow.hiring.workflow``'s job, not this
repository's -- it only enforces the organization boundary, the budget/
headcount aggregates the workflow's checks need, and persists whatever the
tool layer (already checked against the workflow) asks for.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.hiring.model import HiredAgentRow, HireStatus
from deerflow.persistence.organizations.resolution import organization_for_write
from deerflow.runtime.user_context import AUTO, resolve_organization_id, resolve_user_id
from deerflow.utils.time import coerce_iso

_ACTIVE = HireStatus.ACTIVE


def _to_dict(row: HiredAgentRow) -> dict[str, Any]:
    d = row.to_dict()
    for key in ("created_at", "updated_at", "retired_at"):
        val = d.get(key)
        if isinstance(val, datetime):
            d[key] = coerce_iso(val)
    return d


class HiredAgentRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @staticmethod
    def _scope(stmt: Any, organization_id: str | None) -> Any:
        if organization_id is not None:
            return stmt.where(HiredAgentRow.organization_id == organization_id)
        return stmt

    async def create_hire(
        self,
        *,
        agent_name: str,
        title: str,
        manager_agent_name: str,
        depth: int,
        job: str = "",
        kpi: str = "",
        model_family: str = "muse",
        tool_groups: list[str] | None = None,
        private_data: bool = False,
        weekly_token_budget: int = 0,
        hired_by_user_id: str | None = None,
    ) -> dict:
        now = datetime.now(UTC)
        organization_id = organization_for_write(resolve_organization_id(), None, resolve_user_id(AUTO, method_name="HiredAgentRepository.create_hire"))
        row = HiredAgentRow(
            id=uuid.uuid4().hex,
            organization_id=organization_id,
            agent_name=agent_name,
            title=title,
            manager_agent_name=manager_agent_name,
            job=job,
            kpi=kpi,
            model_family=model_family,
            tool_groups=list(tool_groups or []),
            private_data=private_data,
            weekly_token_budget=weekly_token_budget,
            depth=depth,
            status=_ACTIVE,
            hired_by_user_id=hired_by_user_id,
            created_at=now,
            updated_at=now,
        )
        async with self._sf() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return _to_dict(row)

    async def get_hire(self, hire_id: str) -> dict | None:
        organization_id = resolve_organization_id()
        async with self._sf() as session:
            row = await session.get(HiredAgentRow, hire_id)
            if row is None or (organization_id is not None and row.organization_id != organization_id):
                return None
            return _to_dict(row)

    async def get_active_hire_by_agent_name(self, agent_name: str) -> dict | None:
        """The active hire currently holding *agent_name*, if any, in the active organization.

        Used to resolve whether the calling agent may itself act as a hiring
        manager (a depth-2+ manager) -- mirrors
        ``AgentSeatRepository.ratified_seat_for_agent``'s role for depth-1.
        """
        organization_id = resolve_organization_id()
        stmt = self._scope(select(HiredAgentRow), organization_id).where(HiredAgentRow.agent_name == agent_name, HiredAgentRow.status == _ACTIVE)
        stmt = stmt.order_by(HiredAgentRow.created_at.desc()).limit(1)
        async with self._sf() as session:
            result = await session.execute(stmt)
            row = result.scalars().first()
            return _to_dict(row) if row is not None else None

    async def list_reports_of(self, manager_agent_name: str, *, status: str | None = _ACTIVE) -> list[dict]:
        organization_id = resolve_organization_id()
        stmt = self._scope(select(HiredAgentRow), organization_id).where(HiredAgentRow.manager_agent_name == manager_agent_name)
        if status is not None:
            stmt = stmt.where(HiredAgentRow.status == status)
        stmt = stmt.order_by(HiredAgentRow.created_at.asc())
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [_to_dict(r) for r in result.scalars()]

    async def count_active(self) -> int:
        """Org-wide count of active hires, for the owner-set headcount cap."""
        organization_id = resolve_organization_id()
        stmt = self._scope(select(func.count(HiredAgentRow.id)), organization_id).where(HiredAgentRow.status == _ACTIVE)
        async with self._sf() as session:
            return int(await session.scalar(stmt) or 0)

    async def total_carved_budget(self, manager_agent_name: str) -> int:
        """Sum of active reports' ``weekly_token_budget`` under *manager_agent_name*.

        "A hire gets a slice of its manager's weekly token budget, never new
        money" (EXECUTIVE.md) -- this is what a new hire's requested budget is
        checked against, alongside the manager's own budget.
        """
        organization_id = resolve_organization_id()
        stmt = self._scope(select(func.coalesce(func.sum(HiredAgentRow.weekly_token_budget), 0)), organization_id).where(
            HiredAgentRow.manager_agent_name == manager_agent_name,
            HiredAgentRow.status == _ACTIVE,
        )
        async with self._sf() as session:
            return int(await session.scalar(stmt) or 0)

    async def retire(self, hire_id: str, *, retired_by_user_id: str | None = None, now: datetime | None = None) -> dict | None:
        """Persist a retirement; ``None`` for a missing/foreign hire.

        Callers check ``deerflow.hiring.workflow.assert_can_retire`` before
        calling this -- it never re-derives authorization itself.
        """
        organization_id = resolve_organization_id()
        async with self._sf() as session:
            row = await session.get(HiredAgentRow, hire_id)
            if row is None or (organization_id is not None and row.organization_id != organization_id):
                return None
            row.status = HireStatus.RETIRED
            row.retired_by_user_id = retired_by_user_id
            row.retired_at = now or datetime.now(UTC)
            await session.commit()
            await session.refresh(row)
            return _to_dict(row)
