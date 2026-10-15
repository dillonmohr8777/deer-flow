"""pending_actions.fact_check: claim-check report stored at proposal time.

Revision ID: 0050_pending_action_fact_check
Revises: 0049_pending_actions
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0050_pending_action_fact_check"
down_revision: str | Sequence[str] | None = "0049_pending_actions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column() -> bool:
    return any(c["name"] == "fact_check" for c in sa.inspect(op.get_bind()).get_columns("pending_actions"))


def upgrade() -> None:
    if not _has_column():
        op.add_column("pending_actions", sa.Column("fact_check", sa.JSON(), nullable=True))


def downgrade() -> None:
    if _has_column():
        with op.batch_alter_table("pending_actions") as batch:
            batch.drop_column("fact_check")
