"""ceo_desk_digests.

Revision ID: 0048_ceo_desk_digests
Revises: 0047_merge_agent_room_exec

Queue item e14 (ceo-desk): the daily "what shipped, what's stuck, what needs
my yes" digest (``deerflow.ceo_desk.digest``) needs a durable record so
``GET /api/ceo/digest`` can show the most recent one and the scheduled sweep
can tell whether today's digest is already done without redrafting it.
Organization-scoped like ``agent_seats``/``board_threads`` (no DB-level
foreign key by design, matching every other organization reference column in
this schema). New table, so the bootstrap forward-compat floor is unchanged.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0048_ceo_desk_digests"
down_revision: str | Sequence[str] | None = "0047_merge_agent_room_exec"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("ceo_desk_digests"):
        op.create_table(
            "ceo_desk_digests",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("organization_id", sa.String(length=64), nullable=True),
            sa.Column("digest_text", sa.Text(), nullable=False),
            sa.Column("shipped_count", sa.Integer(), nullable=False),
            sa.Column("stuck_count", sa.Integer(), nullable=False),
            sa.Column("needs_my_yes_drafts", sa.Integer(), nullable=False),
            sa.Column("needs_my_yes_ratifications", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_ceo_desk_digests_organization_id", "ceo_desk_digests", ["organization_id"])
        op.create_index("ix_ceo_desk_digests_created_at", "ceo_desk_digests", ["created_at"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("ceo_desk_digests"):
        op.drop_index("ix_ceo_desk_digests_created_at", table_name="ceo_desk_digests")
        op.drop_index("ix_ceo_desk_digests_organization_id", table_name="ceo_desk_digests")
        op.drop_table("ceo_desk_digests")
