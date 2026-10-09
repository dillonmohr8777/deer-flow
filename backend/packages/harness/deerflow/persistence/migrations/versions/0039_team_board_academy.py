"""team_channels, team_messages, academy_progress.

Revision ID: 0039_team_board_academy
Revises: 0038_board_threads

Momentum-internal surfaces: staff-only team channels (kept out of the
client-facing ``board_*`` tables on purpose) and AI Academy lesson
completion. All three are new tables, so the bootstrap forward-compat floor
is unchanged.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0039_team_board_academy"
down_revision: str | Sequence[str] | None = "0038_board_threads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("team_channels"):
        op.create_table(
            "team_channels",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("organization_id", sa.String(length=64), nullable=True),
            sa.Column("slug", sa.String(length=64), nullable=False),
            sa.Column("name", sa.String(length=128), nullable=False),
            sa.Column("topic", sa.String(length=255), nullable=False),
            sa.Column("created_by_user_id", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("organization_id", "slug", name="uq_team_channels_org_slug"),
        )
        op.create_index("ix_team_channels_organization_id", "team_channels", ["organization_id"])

    if not inspector.has_table("team_messages"):
        op.create_table(
            "team_messages",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("channel_id", sa.String(length=64), nullable=False),
            sa.Column("author_user_id", sa.String(length=64), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_team_messages_channel_id", "team_messages", ["channel_id"])
        op.create_index("ix_team_messages_author_user_id", "team_messages", ["author_user_id"])
        op.create_index("ix_team_messages_created_at", "team_messages", ["created_at"])

    if not inspector.has_table("academy_progress"):
        op.create_table(
            "academy_progress",
            sa.Column("organization_id", sa.String(length=64), nullable=False),
            sa.Column("user_id", sa.String(length=64), nullable=False),
            sa.Column("lesson_id", sa.String(length=64), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("organization_id", "user_id", "lesson_id"),
        )
        op.create_index("ix_academy_progress_user_id", "academy_progress", ["user_id"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("academy_progress"):
        op.drop_index("ix_academy_progress_user_id", table_name="academy_progress")
        op.drop_table("academy_progress")

    if inspector.has_table("team_messages"):
        op.drop_index("ix_team_messages_created_at", table_name="team_messages")
        op.drop_index("ix_team_messages_author_user_id", table_name="team_messages")
        op.drop_index("ix_team_messages_channel_id", table_name="team_messages")
        op.drop_table("team_messages")

    if inspector.has_table("team_channels"):
        op.drop_index("ix_team_channels_organization_id", table_name="team_channels")
        op.drop_table("team_channels")
