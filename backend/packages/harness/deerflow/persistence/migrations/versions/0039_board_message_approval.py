"""board_messages.approved_at.

Revision ID: 0039_board_message_approval
Revises: 0038_board_threads

Momo Board follow-up (review finding f20 board-rejected-draft-leak):
per-message approval state, so an unapproved ``momo`` draft stays hidden
from non-admins regardless of the thread's current status (a rejected
draft moved back to ``triaged``/``new``/``closed``, or an earlier draft
superseded by a redraft, never becomes readable just because the thread
later reaches ``drafted`` or ``approved`` again).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0039_board_message_approval"
down_revision: str | Sequence[str] | None = "0038_board_threads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {c["name"] for c in inspector.get_columns("board_messages")}
    if "approved_at" not in columns:
        op.add_column("board_messages", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {c["name"] for c in inspector.get_columns("board_messages")}
    if "approved_at" in columns:
        op.drop_column("board_messages", "approved_at")
