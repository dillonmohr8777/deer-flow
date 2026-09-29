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

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.exec_seats.model import AgentSeatRow, AgentSeatStatus
from deerflow.persistence.organizations.resolution import organization_for_write
from deerflow.persistence.run.model import RunRow
from deerflow.runtime.user_context import AUTO, resolve_organization_id, resolve_user_id
from deerflow.utils.time import coerce_iso

# A run's ``assistant_id`` stays the default (``lead_agent``) when the caller
# names an agent only through ``context.agent_name``/``configurable.agent_name``
# (queue item f95's own left-open gap). ``app.gateway.services.start_run``
# stamps this run-metadata key with that resolved effective identity on every
# run, so ``token_burn_since`` below can count it toward the matching seat's
# burn even when ``assistant_id`` itself never carries the agent's name.
EFFECTIVE_AGENT_NAME_METADATA_KEY = "effective_agent_name"


def _to_dict(row: AgentSeatRow) -> dict[str, Any]:
    d = row.to_dict()
    for key in ("created_at", "updated_at", "paused_at"):
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
        """Create a new claim.

        Does not itself re-derive ``assert_can_claim``'s sequential check
        (callers already do that via ``latest_claim_for_seat``) -- but
        ``uq_agent_seats_open_claim`` (a partial unique index on
        ``(organization_id, seat)`` covering ``status IN ('claimed',
        'ratified')``) is the last line of defense against two concurrent
        claims that both read "no open claim" before either commits. A
        losing insert here raises ``SeatTransitionError``, the same error a
        sequential caller already gets from ``assert_can_claim``.
        """
        now = datetime.now(UTC)
        organization_id = organization_for_write(resolve_organization_id(), None, resolve_user_id(AUTO, method_name="AgentSeatRepository.claim_seat"))
        row = AgentSeatRow(
            id=uuid.uuid4().hex,
            organization_id=organization_id,
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
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                # Confirm the loss was actually the open-claim guard (not,
                # say, an id collision) before reporting it as one.
                still_open = self._scope(select(AgentSeatRow.id), organization_id).where(
                    AgentSeatRow.seat == seat,
                    AgentSeatRow.status.in_((AgentSeatStatus.CLAIMED, AgentSeatStatus.RATIFIED)),
                )
                if (await session.execute(still_open)).first() is not None:
                    from deerflow.exec_seats.workflow import SeatTransitionError

                    raise SeatTransitionError(f"Cannot claim a seat with status {AgentSeatStatus.CLAIMED!r}") from None
                raise
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

    async def latest_claim_for_seat(self, seat: str) -> dict | None:
        """The most recent claim row for *seat* in the active organization, whatever its status.

        ``assert_can_claim`` needs the seat title's *current* status (``None``
        for a title nobody has ever claimed), not just a ratified holder --
        the most recent row can be ``claimed`` (already contested) or
        ``reopened`` (open again after an owner veto).
        """
        organization_id = resolve_organization_id()
        stmt = self._scope(select(AgentSeatRow), organization_id).where(AgentSeatRow.seat == seat)
        stmt = stmt.order_by(AgentSeatRow.created_at.desc(), AgentSeatRow.id.desc()).limit(1)
        async with self._sf() as session:
            result = await session.execute(stmt)
            row = result.scalars().first()
            return _to_dict(row) if row is not None else None

    async def ratified_holder(self, seat: str) -> dict | None:
        """The currently ratified claim for *seat* in the active organization, if any."""
        organization_id = resolve_organization_id()
        stmt = self._scope(select(AgentSeatRow), organization_id).where(AgentSeatRow.seat == seat, AgentSeatRow.status == AgentSeatStatus.RATIFIED)
        stmt = stmt.order_by(AgentSeatRow.updated_at.desc()).limit(1)
        async with self._sf() as session:
            result = await session.execute(stmt)
            row = result.scalars().first()
            return _to_dict(row) if row is not None else None

    async def paused_seat_for_agent(self, agent_name: str) -> dict | None:
        """The currently paused claimed/ratified seat for *agent_name*, if any, in the active organization.

        Matches case- and underscore/hyphen-insensitively against the seat's
        own ``agent_name`` (queue item f95): a seat claimed under ``CMO_Agent``
        must still block a run identifying itself as ``cmo-agent``, the
        normalized form ``build_run_config`` already enforces for an explicit
        ``assistant_id``.
        """
        organization_id = resolve_organization_id()
        normalized = agent_name.strip().lower().replace("_", "-")
        normalized_column = func.replace(func.lower(AgentSeatRow.agent_name), "_", "-")
        stmt = self._scope(select(AgentSeatRow), organization_id).where(
            normalized_column == normalized,
            AgentSeatRow.paused_at.is_not(None),
            AgentSeatRow.status.in_((AgentSeatStatus.CLAIMED, AgentSeatStatus.RATIFIED)),
        )
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

    async def set_paused(self, seat_id: str, *, paused: bool, now: datetime | None = None) -> dict | None:
        """Set or clear ``paused_at``; ``None`` for a missing/foreign seat.

        Orthogonal to ``status`` -- pausing/resuming a seat for a budget
        overrun never touches the claim/ratify/reopen state machine.
        """
        organization_id = resolve_organization_id()
        async with self._sf() as session:
            row = await session.get(AgentSeatRow, seat_id)
            if row is None or (organization_id is not None and row.organization_id != organization_id):
                return None
            row.paused_at = (now or datetime.now(UTC)) if paused else None
            await session.commit()
            await session.refresh(row)
            return _to_dict(row)

    async def token_burn_since(self, *, organization_id: str | None, agent_name: str, since: datetime) -> int:
        """Total tokens every run stamped with *agent_name* has burned since *since*.

        Reads the same ``runs`` table (``RunRow``) the operations console's
        usage ledger reads -- ``assistant_id`` is the run's custom-agent
        identifier, the same value ``AgentSeatRow.agent_name`` stores. A run
        that names its agent only through ``context.agent_name`` (the default
        lead agent's own ``assistant_id`` never changes) is matched instead
        through ``metadata_json[EFFECTIVE_AGENT_NAME_METADATA_KEY]``, the
        resolved identity ``start_run`` stamps on every run.
        """
        stmt = select(func.coalesce(func.sum(RunRow.total_tokens), 0)).where(
            or_(RunRow.assistant_id == agent_name, RunRow.metadata_json[EFFECTIVE_AGENT_NAME_METADATA_KEY].as_string() == agent_name),
            RunRow.created_at >= since,
        )
        if organization_id is not None:
            stmt = stmt.where(RunRow.organization_id == organization_id)
        async with self._sf() as session:
            return int(await session.scalar(stmt) or 0)
