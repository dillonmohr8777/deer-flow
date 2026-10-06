"""pending_actions: the approvals inbox.

Revision ID: 0049_pending_actions
Revises: 0048_repair_audit_events

Agents propose outbound actions (Slack message, client email, ad change) as
rows here; a human edits and approves them; only approved rows execute.
``original_payload`` is frozen at proposal time for the audit trail. Rows are
owner- and organization-scoped like every other tenant table.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0049_pending_actions"
down_revision: str | Sequence[str] | None = "0048_repair_audit_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("pending_actions"):
        return
    op.create_table(
        "pending_actions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("organization_id", sa.String(length=64), nullable=True),
        sa.Column("action_type", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("target", sa.String(length=512), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("original_payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("thread_id", sa.String(length=64), nullable=True),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("agent_name", sa.String(length=128), nullable=True),
        sa.Column("decided_by", sa.String(length=64), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("execution_result", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pending_actions_user_id", "pending_actions", ["user_id"])
    op.create_index("ix_pending_actions_organization_id", "pending_actions", ["organization_id"])
    op.create_index("ix_pending_actions_user_status", "pending_actions", ["user_id", "status"])


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("pending_actions"):
        op.drop_index("ix_pending_actions_user_status", table_name="pending_actions")
        op.drop_index("ix_pending_actions_organization_id", table_name="pending_actions")
        op.drop_index("ix_pending_actions_user_id", table_name="pending_actions")
        op.drop_table("pending_actions")
