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

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.exec_seats.model import AgentSeatRow, AgentSeatStatus
from deerflow.persistence.exec_seats.sql import EFFECTIVE_AGENT_NAME_METADATA_KEY
from deerflow.persistence.hiring.model import HiredAgentRow, HireStatus
from deerflow.persistence.organizations.resolution import organization_for_write
from deerflow.persistence.run.model import RunRow
from deerflow.runtime.user_context import AUTO, resolve_organization_id, resolve_user_id
from deerflow.utils.time import coerce_iso

_ACTIVE = HireStatus.ACTIVE


def _to_dict(row: HiredAgentRow) -> dict[str, Any]:
    d = row.to_dict()
    for key in ("created_at", "updated_at", "retired_at", "last_kpi_check_at"):
        val = d.get(key)
        if isinstance(val, datetime):
            d[key] = coerce_iso(val)
    return d


def _normalize(name: str) -> str:
    """Case/underscore-insensitive identity match, mirroring
    ``AgentSeatRepository.paused_seat_for_agent``'s normalization -- an
    ``agent_name``/``manager_agent_name`` of ``CEO-Agent`` and ``ceo_agent``
    must be treated as the same identity everywhere, not just where a caller
    happened to normalize (review finding, high 2)."""
    return name.strip().lower().replace("_", "-")


def _normalized_column(col: Any) -> Any:
    return func.replace(func.lower(col), "_", "-")


def _org_lock_key(organization_id: str | None) -> int:
    """A stable 63-bit key for ``pg_advisory_xact_lock``, derived from *organization_id*.

    Mirrors ``ChannelConnectionRepository._oauth_scope_lock_key``. ``None``
    (internal/no-org context) still gets a fixed key, serializing every
    no-org hire attempt against every other -- the safe, coarser default.
    """
    digest = hashlib.sha256(f"hiring:{organization_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big") & 0x7FFFFFFFFFFFFFFF


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

    async def create_hire_atomic(
        self,
        *,
        agent_name: str,
        title: str,
        manager_agent_name: str,
        manager_depth: int,
        max_org_depth: int,
        manager_tool_groups: list[str] | None,
        known_tool_groups: frozenset[str] | None,
        manager_cleared_for_private_data: bool,
        manager_weekly_token_budget: int,
        headcount_cap: int,
        job: str = "",
        kpi: str = "",
        model_family: str = "muse",
        tool_groups: list[str] | None = None,
        private_data: bool = False,
        weekly_token_budget: int = 0,
        hired_by_user_id: str | None = None,
    ) -> dict:
        """Check every ``deerflow.hiring.workflow.assert_can_hire`` guard and insert, atomically.

        Review finding (high 3): a plain check-then-insert lets N concurrent
        hires each read the same stale headcount/budget/name-availability and
        all pass. This locks the organization first -- a transaction-scoped
        Postgres advisory lock (``pg_advisory_xact_lock``, released
        automatically on commit/rollback), or SQLite's own writer lock via
        ``BEGIN IMMEDIATE`` (same idiom as
        ``ScheduledTaskRunRepository.claim_queued_run`` and
        ``ProjectDocumentRepository.insert_active``) -- before re-reading the
        racy aggregates inside this transaction, so two concurrent callers in
        the same organization can never both pass the same window. Raises
        whatever ``assert_can_hire`` raises, or ``HireNameConflictError`` for
        a name collision (checked against both active hires and ratified
        seats, case/underscore-insensitive -- review finding, high 2); either
        way the transaction is never committed, so nothing is persisted.
        """
        from deerflow.hiring.workflow import HireNameConflictError, assert_can_hire

        organization_id = organization_for_write(resolve_organization_id(), None, resolve_user_id(AUTO, method_name="HiredAgentRepository.create_hire_atomic"))
        normalized_name = _normalize(agent_name)
        normalized_manager = _normalize(manager_agent_name)
        name_scope = (HiredAgentRow.organization_id == organization_id) if organization_id is not None else HiredAgentRow.organization_id.is_(None)
        seat_scope = (AgentSeatRow.organization_id == organization_id) if organization_id is not None else AgentSeatRow.organization_id.is_(None)

        async with self._sf() as session:
            dialect = session.get_bind().dialect.name
            if dialect == "postgresql":
                await session.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": _org_lock_key(organization_id)})
            elif dialect == "sqlite":
                # Same reasoning as ScheduledTaskRunRepository.claim_queued_run:
                # a deferred SQLite transaction only reserves the writer at
                # the final INSERT, too late to protect the counts read
                # before it. BEGIN IMMEDIATE takes the writer up front.
                await session.execute(text("BEGIN IMMEDIATE"))

            hire_conflict = (await session.execute(select(HiredAgentRow.id).where(name_scope, _normalized_column(HiredAgentRow.agent_name) == normalized_name, HiredAgentRow.status == _ACTIVE).limit(1))).first()
            if hire_conflict is not None:
                raise HireNameConflictError(f"{agent_name!r} is already an active report in this organization.")

            seat_conflict = (await session.execute(select(AgentSeatRow.id).where(seat_scope, _normalized_column(AgentSeatRow.agent_name) == normalized_name, AgentSeatRow.status == AgentSeatStatus.RATIFIED).limit(1))).first()
            if seat_conflict is not None:
                raise HireNameConflictError(f"{agent_name!r} already names a titled employee in this organization.")

            existing_headcount = int((await session.execute(select(func.count(HiredAgentRow.id)).where(name_scope, HiredAgentRow.status == _ACTIVE))).scalar() or 0)
            carved_budget_so_far = int(
                (
                    await session.execute(select(func.coalesce(func.sum(HiredAgentRow.weekly_token_budget), 0)).where(name_scope, _normalized_column(HiredAgentRow.manager_agent_name) == normalized_manager, HiredAgentRow.status == _ACTIVE))
                ).scalar()
                or 0
            )

            assert_can_hire(
                manager_depth=manager_depth,
                max_org_depth=max_org_depth,
                manager_tool_groups=manager_tool_groups,
                requested_tool_groups=tool_groups or [],
                known_tool_groups=known_tool_groups,
                manager_cleared_for_private_data=manager_cleared_for_private_data,
                requested_model_family=model_family,
                requested_private_data=private_data,
                manager_weekly_token_budget=manager_weekly_token_budget,
                carved_budget_so_far=carved_budget_so_far,
                requested_weekly_token_budget=weekly_token_budget,
                existing_headcount=existing_headcount,
                headcount_cap=headcount_cap,
            )

            now = datetime.now(UTC)
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
                depth=manager_depth + 1,
                status=_ACTIVE,
                hired_by_user_id=hired_by_user_id,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return _to_dict(row)

    async def list_hires(self, *, status: str | None = _ACTIVE) -> list[dict]:
        """List hires in the active organization, or every organization's when called
        outside any storage context (the same "no ambient org -> unscoped" shape
        ``AgentSeatRepository.list_seats`` uses for its own cross-org sweep)."""
        organization_id = resolve_organization_id()
        stmt = self._scope(select(HiredAgentRow), organization_id)
        if status is not None:
            stmt = stmt.where(HiredAgentRow.status == status)
        stmt = stmt.order_by(HiredAgentRow.created_at.asc(), HiredAgentRow.id.asc())
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [_to_dict(r) for r in result.scalars()]

    async def last_activity_at(self, *, organization_id: str | None, agent_name: str) -> datetime | None:
        """The most recent run timestamp for *agent_name*, or ``None`` if it has never run.

        Mirrors ``AgentSeatRepository.token_burn_since``'s matching (both a raw
        ``RunRow.assistant_id`` and the ``effective_agent_name`` metadata
        ``start_run`` stamps for a run that only ever named its agent through
        ``context.agent_name``), case/underscore-insensitively, so the idle
        clock reflects every run actually attributable to this hire.
        """
        normalized = _normalize(agent_name)
        normalized_assistant_id = _normalized_column(RunRow.assistant_id)
        normalized_effective_agent_name = _normalized_column(RunRow.metadata_json[EFFECTIVE_AGENT_NAME_METADATA_KEY].as_string())
        stmt = select(func.max(RunRow.created_at)).where(or_(normalized_assistant_id == normalized, normalized_effective_agent_name == normalized))
        if organization_id is not None:
            stmt = stmt.where(RunRow.organization_id == organization_id)
        async with self._sf() as session:
            return await session.scalar(stmt)

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
        Case/underscore-insensitive, matching that method's normalization.
        """
        organization_id = resolve_organization_id()
        stmt = self._scope(select(HiredAgentRow), organization_id).where(_normalized_column(HiredAgentRow.agent_name) == _normalize(agent_name), HiredAgentRow.status == _ACTIVE)
        stmt = stmt.order_by(HiredAgentRow.created_at.desc()).limit(1)
        async with self._sf() as session:
            result = await session.execute(stmt)
            row = result.scalars().first()
            return _to_dict(row) if row is not None else None

    async def list_reports_of(self, manager_agent_name: str, *, status: str | None = _ACTIVE) -> list[dict]:
        """Case/underscore-insensitive, matching ``get_active_hire_by_agent_name``."""
        organization_id = resolve_organization_id()
        stmt = self._scope(select(HiredAgentRow), organization_id).where(_normalized_column(HiredAgentRow.manager_agent_name) == _normalize(manager_agent_name))
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
        checked against, alongside the manager's own budget. Case/underscore-
        insensitive, matching ``get_active_hire_by_agent_name``.
        """
        organization_id = resolve_organization_id()
        stmt = self._scope(select(func.coalesce(func.sum(HiredAgentRow.weekly_token_budget), 0)), organization_id).where(
            _normalized_column(HiredAgentRow.manager_agent_name) == _normalize(manager_agent_name),
            HiredAgentRow.status == _ACTIVE,
        )
        async with self._sf() as session:
            return int(await session.scalar(stmt) or 0)

    async def record_kpi_check_result(self, hire_id: str, *, met: bool, now: datetime | None = None) -> dict | None:
        """Record this week's KPI review for *hire_id*; ``None`` for a missing/foreign hire.

        Mirrors ``AgentSeatRepository.record_scorecard_result``: a "met"
        review resets ``missed_kpi_checks`` to 0, a "missed" one increments
        it. Either way ``last_kpi_check_at`` advances, so
        ``deerflow.hiring.kpi_review.evaluate_hire_kpi`` does not re-evaluate
        this hire again until next week regardless of sweep frequency.
        """
        organization_id = resolve_organization_id()
        async with self._sf() as session:
            row = await session.get(HiredAgentRow, hire_id)
            if row is None or (organization_id is not None and row.organization_id != organization_id):
                return None
            row.missed_kpi_checks = 0 if met else row.missed_kpi_checks + 1
            row.last_kpi_check_at = now or datetime.now(UTC)
            await session.commit()
            await session.refresh(row)
            return _to_dict(row)

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
