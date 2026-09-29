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

from sqlalchemy import func, select
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
    for key in ("created_at", "updated_at", "paused_at", "last_scorecard_at"):
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
        model_family: str = "muse",
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
            model_family=model_family,
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

    async def ratified_seat_for_agent(self, agent_name: str) -> dict | None:
        """The ratified seat currently held by *agent_name*, if any, in the active organization.

        Resolves whether an agent is a depth-1 hiring manager (queue item
        e12): a titled employee. Case/underscore-insensitive, matching
        ``paused_seat_for_agent``'s normalization.
        """
        organization_id = resolve_organization_id()
        normalized = agent_name.strip().lower().replace("_", "-")
        normalized_column = func.replace(func.lower(AgentSeatRow.agent_name), "_", "-")
        stmt = self._scope(select(AgentSeatRow), organization_id).where(
            normalized_column == normalized,
            AgentSeatRow.status == AgentSeatStatus.RATIFIED,
        )
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

        A caller with no resolved organization (auth-disabled/internal, a
        seat claimed with no active org) must match only a seat claimed the
        same way -- ``organization_id IS NULL`` -- never another
        organization's seat and never every seat regardless of organization.
        ``_scope``'s "``None`` = no filter" convention is right for
        admin-style listing but was wrong here twice over (queue item f99,
        then f123's review of the first fix): failing open let a null-org
        caller 429 an unrelated org's run and leak that seat's title;
        failing closed made every null-org seat's pause silently
        unenforceable, since a seat claimed with no active org is itself
        stored with ``organization_id=None`` (``organization_for_write``'s
        quarantine marker), not a case that never occurs.
        """
        organization_id = resolve_organization_id()
        normalized = agent_name.strip().lower().replace("_", "-")
        normalized_column = func.replace(func.lower(AgentSeatRow.agent_name), "_", "-")
        org_filter = AgentSeatRow.organization_id.is_(None) if organization_id is None else AgentSeatRow.organization_id == organization_id
        stmt = select(AgentSeatRow).where(
            org_filter,
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

    async def record_scorecard_result(self, seat_id: str, *, success: bool, now: datetime | None = None) -> dict | None:
        """Record this week's scorecard check for *seat_id*; ``None`` for a missing/foreign seat.

        A successful post resets ``missed_scorecards`` to 0; a miss increments
        it. Either way ``last_scorecard_at`` advances, so the weekly sweep
        (``deerflow.exec_seats.scorecard.evaluate_seat_scorecard``) does not
        re-evaluate this seat again until next week regardless of how often
        the loop itself runs.
        """
        organization_id = resolve_organization_id()
        async with self._sf() as session:
            row = await session.get(AgentSeatRow, seat_id)
            if row is None or (organization_id is not None and row.organization_id != organization_id):
                return None
            row.missed_scorecards = 0 if success else row.missed_scorecards + 1
            row.last_scorecard_at = now or datetime.now(UTC)
            await session.commit()
            await session.refresh(row)
            return _to_dict(row)

    async def token_burn_since(self, *, organization_id: str | None, agent_name: str, since: datetime) -> int:
        """Total tokens every run stamped with *agent_name* has burned since *since*.

        Reads the same ``runs`` table (``RunRow``) the operations console's
        usage ledger reads. ``RunRow.assistant_id`` is the raw, client-chosen
        ``body.assistant_id`` -- not necessarily the agent that actually ran,
        since an explicit ``configurable``/``context.agent_name`` overrides it
        (queue item f95's own left-open gap). Each run's real identity is
        ``metadata_json[EFFECTIVE_AGENT_NAME_METADATA_KEY]`` (the resolved
        identity ``start_run`` stamps on every run) when present, falling back
        to ``assistant_id`` only for older rows written before that stamp
        existed. One identity per row, never both (f98 review of f97): an
        ``or_`` across both columns let a single run with a diverging
        ``assistant_id``/``agent_name`` double-count and misattribute burn to
        two different seats.

        Matched case- and underscore/hyphen-insensitively (f97 review), the
        same normalization ``paused_seat_for_agent`` already applies: a raw
        ``RunRow.assistant_id`` of ``CMO_Agent`` or a stamped identity of
        ``CMO-Agent`` must count toward a seat claimed as ``cmo-agent``
        exactly like the exact-cased form would.

        ``organization_id=None`` is never "every organization's burn" -- a
        seat claimed with no active org is itself stored with
        ``organization_id=None`` (``organization_for_write``'s quarantine
        marker, not a case that never occurs), so a null-org seat's own
        burn must still count. A null-org caller (queue item f99, then
        f123's review of the first fix) matches only null-org runs, never
        a sum across every org's same-named agent.
        """
        normalized = agent_name.strip().lower().replace("_", "-")
        effective_identity = func.coalesce(RunRow.metadata_json[EFFECTIVE_AGENT_NAME_METADATA_KEY].as_string(), RunRow.assistant_id)
        normalized_identity = func.replace(func.lower(effective_identity), "_", "-")
        org_filter = RunRow.organization_id.is_(None) if organization_id is None else RunRow.organization_id == organization_id
        stmt = select(func.coalesce(func.sum(RunRow.total_tokens), 0)).where(
            org_filter,
            normalized_identity == normalized,
            RunRow.created_at >= since,
        )
        async with self._sf() as session:
            return int(await session.scalar(stmt) or 0)
