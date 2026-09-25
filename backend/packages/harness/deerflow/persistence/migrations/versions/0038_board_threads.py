"""board_threads, board_messages.

Revision ID: 0038_board_threads
Revises: 0037_pat_organization

Momo Board (Workspace Phase 4 item b1): client posts, tickets, concerns and
DMs, triaged and drafted by Momo, replied only after owner approval.
``board_threads`` is organization- and client-scoped like ``clients`` itself
(no DB-level foreign key by design, matching every other client/organization
reference column in this schema); ``board_messages`` holds the ordered
message history of a thread. Both are new tables, so the bootstrap
forward-compat floor is unchanged.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0038_board_threads"
down_revision: str | Sequence[str] | None = "0037_pat_organization"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("board_threads"):
        op.create_table(
            "board_threads",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("organization_id", sa.String(length=64), nullable=True),
            sa.Column("client_id", sa.String(length=64), nullable=True),
            sa.Column("kind", sa.String(length=16), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("subject", sa.String(length=255), nullable=False),
            sa.Column("created_by_user_id", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_board_threads_organization_id", "board_threads", ["organization_id"])
        op.create_index("ix_board_threads_client_id", "board_threads", ["client_id"])
        op.create_index("ix_board_threads_status", "board_threads", ["status"])
        op.create_index("ix_board_threads_created_by_user_id", "board_threads", ["created_by_user_id"])

    if not inspector.has_table("board_messages"):
        op.create_table(
            "board_messages",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("thread_id", sa.String(length=64), nullable=False),
            sa.Column("author_kind", sa.String(length=16), nullable=False),
            sa.Column("author_user_id", sa.String(length=64), nullable=True),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_board_messages_thread_id", "board_messages", ["thread_id"])
        op.create_index("ix_board_messages_author_user_id", "board_messages", ["author_user_id"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("board_messages"):
        op.drop_index("ix_board_messages_author_user_id", table_name="board_messages")
        op.drop_index("ix_board_messages_thread_id", table_name="board_messages")
        op.drop_table("board_messages")

    if inspector.has_table("board_threads"):
        op.drop_index("ix_board_threads_created_by_user_id", table_name="board_threads")
        op.drop_index("ix_board_threads_status", table_name="board_threads")
        op.drop_index("ix_board_threads_client_id", table_name="board_threads")
        op.drop_index("ix_board_threads_organization_id", table_name="board_threads")
        op.drop_table("board_threads")
