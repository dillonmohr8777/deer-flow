"""ORM model for Momentum agent hires (queue item e12, hiring).

EXECUTIVE.md's Hiring section: any titled employee (an ``agent_seats``
ratified holder) or one of its own active hires may hire and retire its own
reports, no approval needed. Organization-scoped like ``AgentSeatRow`` (no
DB-level foreign key, the same "no FK by design" convention used throughout
this package). ``manager_agent_name`` is the hiring agent's own identity --
either a ratified seat holder (depth 1) or another active hire (depth 2+),
resolved by ``deerflow.tools.hire_tools`` at hire time, not by this table.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import JSON, Boolean, DateTime, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base


def _utc_now() -> datetime:
    return datetime.now(UTC)


class HireStatus(StrEnum):
    """Canonical status vocabulary for a hire."""

    ACTIVE = "active"
    RETIRED = "retired"


class HiredAgentRow(Base):
    __tablename__ = "hired_agents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    agent_name: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(String(128), default="")
    manager_agent_name: Mapped[str] = mapped_column(String(128), index=True)
    job: Mapped[str] = mapped_column(Text, default="")
    kpi: Mapped[str] = mapped_column(Text, default="")
    # "Muse 1.3 by default. Luna only when the job needs private data or
    # independent review" (EXECUTIVE.md). Gates whether this hire may itself
    # hold ``private_data`` access, and whether it may act as a Luna manager
    # for one of its own future reports.
    model_family: Mapped[str] = mapped_column(String(16), default="muse")
    tool_groups: Mapped[list] = mapped_column(JSON, default=list)
    # "No escalation" (EXECUTIVE.md): a hire's tools and data access are a
    # subset of its manager's, so a hire with private_data=True can only ever
    # have been created by a Luna manager -- deerflow.hiring.workflow enforces
    # this at hire time, this column is just the durable record of the grant.
    private_data: Mapped[bool] = mapped_column(Boolean, default=False)
    weekly_token_budget: Mapped[int] = mapped_column(Integer, default=0)
    # 1 = a ratified agent_seats holder (a titled employee); a hire made by a
    # depth-N manager is depth N+1. Capped by HiringConfig.max_org_depth.
    depth: Mapped[int] = mapped_column(Integer, default=2)
    status: Mapped[str] = mapped_column(String(16), default=HireStatus.ACTIVE, index=True)
    hired_by_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    retired_by_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, onupdate=_utc_now)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_hired_agents_org_manager", "organization_id", "manager_agent_name"),
        # Defense in depth alongside create_hire_atomic's transaction-scoped
        # lock (review finding, high 3): at most one *active* row per
        # (organization_id, agent_name), case-sensitive (the atomic path's
        # own normalized, locked check is what actually closes the
        # case-variant race -- this index catches a direct create_hire call
        # that bypasses it). Must live in ORM __table_args__, not just the
        # migration, for the empty-DB create_all() bootstrap path -- same
        # reasoning as uq_agent_seats_open_claim.
        Index(
            "uq_hired_agents_active_agent_name",
            "organization_id",
            "agent_name",
            unique=True,
            sqlite_where=text("status = 'active'"),
            postgresql_where=text("status = 'active'"),
        ),
    )
