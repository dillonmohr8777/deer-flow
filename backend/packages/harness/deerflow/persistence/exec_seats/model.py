"""ORM model for Momentum agent seats (queue item e9, exec-seats).

``EXECUTIVE.md``'s titles carry no authority by themselves; ``agent_seats``
is the durable record of who currently holds one and how it got there.
Organization-scoped like ``BoardThreadRow``/``ClientRow`` (no DB-level
foreign key, the same "no FK by design" convention used throughout this
package).
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import DateTime, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base


def _utc_now() -> datetime:
    return datetime.now(UTC)


class AgentSeatStatus(StrEnum):
    """Canonical status vocabulary for an agent seat."""

    CLAIMED = "claimed"
    RATIFIED = "ratified"
    REOPENED = "reopened"


class AgentSeatRow(Base):
    __tablename__ = "agent_seats"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    seat: Mapped[str] = mapped_column(String(128), index=True)
    agent_name: Mapped[str] = mapped_column(String(128))
    scope: Mapped[str] = mapped_column(Text, default="")
    kpi: Mapped[str] = mapped_column(Text, default="")
    weekly_token_budget: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default=AgentSeatStatus.CLAIMED, index=True)
    claimed_by_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ratified_by_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, onupdate=_utc_now)

    __table_args__ = (
        # At most one open (claimed or ratified) row per (organization_id, seat):
        # closes the race the tool layer's assert_can_claim alone can't (two
        # concurrent exec_claim_seat calls both reading "no open claim" before
        # either commits). A losing insert raises IntegrityError, which the
        # repository translates into the same SeatTransitionError the
        # sequential check already raises. Must live in ORM __table_args__
        # (not just the migration) because the empty-DB bootstrap path runs
        # create_all() + stamp head and never executes the migration that
        # also defines this index -- same reasoning as
        # uq_scheduled_task_run_active.
        Index(
            "uq_agent_seats_open_claim",
            "organization_id",
            "seat",
            unique=True,
            sqlite_where=text("status IN ('claimed', 'ratified')"),
            postgresql_where=text("status IN ('claimed', 'ratified')"),
        ),
    )
