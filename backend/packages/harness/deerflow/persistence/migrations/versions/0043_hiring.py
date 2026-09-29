"""agent_seats.model_family, hired_agents.

Revision ID: 0043_hiring
Revises: 0042_agent_seats_scorecard

Queue item e12 (agent-hiring): EXECUTIVE.md's Hiring section -- any titled
employee (an ``agent_seats`` ratified holder) or one of its own active hires
may hire and retire its own reports, no approval needed. ``model_family`` on
``agent_seats`` records whether a titled seat holder is itself a Luna or
Muse employee (defaults to the least-privileged ``muse`` for every seat
claimed before this column existed, or that never specifies it) -- the fact
the "only a Luna manager may hire into private data" check needs for a
depth-1 manager. ``hired_agents`` is the durable record of every hire: its
manager, its own model family, its tools (a subset of its manager's), its
budget (carved from its manager's), and its depth in the hire chain (capped
by ``HiringConfig.max_org_depth``). Organization-scoped like ``agent_seats``
(no DB-level foreign key by design).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0043_hiring"
down_revision: str | Sequence[str] | None = "0042_agent_seats_scorecard"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_add_column

    safe_add_column("agent_seats", sa.Column("model_family", sa.String(length=16), nullable=False, server_default="muse"))

    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("hired_agents"):
        op.create_table(
            "hired_agents",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("organization_id", sa.String(length=64), nullable=True),
            sa.Column("agent_name", sa.String(length=128), nullable=False),
            sa.Column("title", sa.String(length=128), nullable=False),
            sa.Column("manager_agent_name", sa.String(length=128), nullable=False),
            sa.Column("job", sa.Text(), nullable=False),
            sa.Column("kpi", sa.Text(), nullable=False),
            sa.Column("model_family", sa.String(length=16), nullable=False),
            sa.Column("tool_groups", sa.JSON(), nullable=False),
            sa.Column("private_data", sa.Boolean(), nullable=False),
            sa.Column("weekly_token_budget", sa.Integer(), nullable=False),
            sa.Column("depth", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("hired_by_user_id", sa.String(length=64), nullable=True),
            sa.Column("retired_by_user_id", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_hired_agents_organization_id", "hired_agents", ["organization_id"])
        op.create_index("ix_hired_agents_agent_name", "hired_agents", ["agent_name"])
        op.create_index("ix_hired_agents_manager_agent_name", "hired_agents", ["manager_agent_name"])
        op.create_index("ix_hired_agents_status", "hired_agents", ["status"])
        op.create_index("ix_hired_agents_org_manager", "hired_agents", ["organization_id", "manager_agent_name"])
        # Defense in depth alongside create_hire_atomic's transaction-scoped
        # lock (review finding, high 3): see AgentSeatRow's matching
        # uq_agent_seats_open_claim / model.py's own comment on this index.
        op.create_index(
            "uq_hired_agents_active_agent_name",
            "hired_agents",
            ["organization_id", "agent_name"],
            unique=True,
            sqlite_where=sa.text("status = 'active'"),
            postgresql_where=sa.text("status = 'active'"),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("hired_agents"):
        op.drop_index("uq_hired_agents_active_agent_name", table_name="hired_agents")
        op.drop_index("ix_hired_agents_org_manager", table_name="hired_agents")
        op.drop_index("ix_hired_agents_status", table_name="hired_agents")
        op.drop_index("ix_hired_agents_manager_agent_name", table_name="hired_agents")
        op.drop_index("ix_hired_agents_agent_name", table_name="hired_agents")
        op.drop_index("ix_hired_agents_organization_id", table_name="hired_agents")
        op.drop_table("hired_agents")

    from deerflow.persistence.migrations._helpers import safe_drop_column

    safe_drop_column("agent_seats", "model_family")
