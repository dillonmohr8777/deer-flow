"""agent_seats.

Revision ID: 0040_agent_seats
Revises: 0039_team_board_academy

Momentum agent seats (queue item e9, exec-seats): the durable record of who
holds an ``EXECUTIVE.md`` title, and how (claimed -> ratified -> reopened).
Organization-scoped like ``board_threads``/``clients`` (no DB-level foreign
key by design, matching every other organization reference column in this
schema). New table, so the bootstrap forward-compat floor is unchanged.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0040_agent_seats"
down_revision: str | Sequence[str] | None = "0039_team_board_academy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("agent_seats"):
        op.create_table(
            "agent_seats",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("organization_id", sa.String(length=64), nullable=True),
            sa.Column("seat", sa.String(length=128), nullable=False),
            sa.Column("agent_name", sa.String(length=128), nullable=False),
            sa.Column("scope", sa.Text(), nullable=False),
            sa.Column("kpi", sa.Text(), nullable=False),
            sa.Column("weekly_token_budget", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("claimed_by_user_id", sa.String(length=64), nullable=True),
            sa.Column("ratified_by_user_id", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_agent_seats_organization_id", "agent_seats", ["organization_id"])
        op.create_index("ix_agent_seats_seat", "agent_seats", ["seat"])
        op.create_index("ix_agent_seats_status", "agent_seats", ["status"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("agent_seats"):
        op.drop_index("ix_agent_seats_status", table_name="agent_seats")
        op.drop_index("ix_agent_seats_seat", table_name="agent_seats")
        op.drop_index("ix_agent_seats_organization_id", table_name="agent_seats")
        op.drop_table("agent_seats")
