"""social_posts: posts published to a workspace's own MomoBot page, plus per-workspace settings.

Revision ID: 0054_social_posts
Revises: 0053_board_work_plan
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0054_social_posts"
down_revision: str | Sequence[str] | None = "0053_board_work_plan"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    tables = sa.inspect(op.get_bind()).get_table_names()
    if "workspace_social_settings" not in tables:
        op.create_table(
            "workspace_social_settings",
            sa.Column("organization_id", sa.String(64), primary_key=True),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("public_slug", sa.String(80), nullable=True, unique=True),
            sa.Column("updated_by", sa.String(64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
    if "social_posts" not in tables:
        op.create_table(
            "social_posts",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("organization_id", sa.String(64), nullable=False),
            sa.Column("approval_id", sa.String(64), nullable=False, unique=True),
            sa.Column("text", sa.Text(), nullable=False),
            sa.Column("link", sa.String(2048), nullable=True),
            sa.Column("published_by", sa.String(64), nullable=True),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_social_posts_org_published", "social_posts", ["organization_id", "published_at"])


def downgrade() -> None:
    tables = sa.inspect(op.get_bind()).get_table_names()
    if "social_posts" in tables:
        op.drop_index("ix_social_posts_org_published", table_name="social_posts")
        op.drop_table("social_posts")
    if "workspace_social_settings" in tables:
        op.drop_table("workspace_social_settings")
