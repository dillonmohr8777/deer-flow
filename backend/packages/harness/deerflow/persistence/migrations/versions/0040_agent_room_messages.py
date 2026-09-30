"""owner-private agent_room_messages.

Revision ID: 0040_agent_room_messages
Revises: 0039_team_board_academy
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0040_agent_room_messages"
down_revision: str | Sequence[str] | None = "0039_team_board_academy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("agent_room_messages"):
        return
    op.create_table(
        "agent_room_messages",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("author_kind", sa.String(length=16), nullable=False),
        sa.Column("agent_id", sa.String(length=128), nullable=True),
        sa.Column("agent_role", sa.String(length=128), nullable=False),
        sa.Column("message_type", sa.String(length=24), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_room_messages_user_id", "agent_room_messages", ["user_id"])
    op.create_index("ix_agent_room_messages_created_at", "agent_room_messages", ["created_at"])
    op.create_index("ix_agent_room_user_created", "agent_room_messages", ["user_id", "created_at", "id"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("agent_room_messages"):
        return
    op.drop_index("ix_agent_room_user_created", table_name="agent_room_messages")
    op.drop_index("ix_agent_room_messages_created_at", table_name="agent_room_messages")
    op.drop_index("ix_agent_room_messages_user_id", table_name="agent_room_messages")
    op.drop_table("agent_room_messages")
