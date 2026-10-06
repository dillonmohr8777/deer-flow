"""client_corrections: per-client ledger of reviewer edits made before approval.

Revision ID: 0051_client_corrections
Revises: 0050_pending_action_fact_check
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0051_client_corrections"
down_revision: str | Sequence[str] | None = "0050_pending_action_fact_check"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if "client_corrections" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "client_corrections",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("organization_id", sa.String(64), nullable=True),
        sa.Column("client_key", sa.String(160), nullable=False),
        sa.Column("action_type", sa.String(32), nullable=False),
        sa.Column("approval_id", sa.String(64), nullable=False),
        sa.Column("original", sa.JSON(), nullable=False),
        sa.Column("edited", sa.JSON(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("approver", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_client_corrections_user_client_created", "client_corrections", ["user_id", "client_key", "created_at"])


def downgrade() -> None:
    if "client_corrections" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_index("ix_client_corrections_user_client_created", table_name="client_corrections")
        op.drop_table("client_corrections")
