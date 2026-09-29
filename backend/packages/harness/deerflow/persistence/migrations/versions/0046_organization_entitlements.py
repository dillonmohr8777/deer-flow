"""organization_entitlements.

Revision ID: 0046_organization_entitlements
Revises: 0045_board_thread_triage

M4 entitlement gate (task e6, design in docs/momo-week/m4-entitlement.md from
task c2). One row per (organization_id, key): a gate key (console.read,
runs.create, runs.cancel, agents.manage, schedules.manage) grants by row
existence + status="active"; a limit key (projects.max, workflows.max,
brands.max, repair_minutes.monthly) additionally carries limit_value. New
table, additive and nullable everywhere except the composite key, so the
bootstrap forward-compat floor is unchanged and no route calls the evaluator
until it is wired in (dead code path until entitlements.enabled=true).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0046_organization_entitlements"
down_revision: str | Sequence[str] | None = "0045_board_thread_triage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "organization_entitlements"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(_TABLE):
        op.create_table(
            _TABLE,
            sa.Column("organization_id", sa.String(length=64), nullable=False),
            sa.Column("key", sa.String(length=64), nullable=False),
            sa.Column("limit_value", sa.Integer(), nullable=True),
            sa.Column("source", sa.String(length=32), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("organization_id", "key"),
        )
        op.create_index(f"ix_{_TABLE}_organization_id", _TABLE, ["organization_id"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table(_TABLE):
        op.drop_index(f"ix_{_TABLE}_organization_id", table_name=_TABLE)
        op.drop_table(_TABLE)
