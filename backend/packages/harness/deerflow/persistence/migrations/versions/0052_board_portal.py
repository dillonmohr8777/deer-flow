"""Opt-in client portal; existing messages remain internal.

Revision ID: 0052_board_portal
Revises: 0051_client_corrections
"""

import sqlalchemy as sa
from alembic import op

revision = "0052_board_portal"
down_revision = "0051_client_corrections"
branch_labels = depends_on = None


def upgrade():
    op.add_column("organizations", sa.Column("customer_client_id", sa.String(64), nullable=True))
    op.add_column("threads_meta", sa.Column("client_actor_id", sa.String(64), nullable=True))
    op.create_index("ix_threads_meta_client_actor_id", "threads_meta", ["client_actor_id"])
    op.add_column("board_messages", sa.Column("visibility", sa.String(16), nullable=False, server_default="internal"))
    op.add_column("board_messages", sa.Column("attachments", sa.JSON(), nullable=True))
    op.create_table(
        "board_portal",
        sa.Column("thread_id", sa.String(64), primary_key=True),
        sa.Column("organization_id", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(64), nullable=False),
        sa.Column("submission_key", sa.String(64), nullable=False),
        sa.Column("submission_hash", sa.String(64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        *[sa.Column(k, sa.String(64), nullable=True) for k in ("draft_id", "approval_id", "published_id", "client_chat_id", "work_chat_id", "work_run_id")],
        sa.UniqueConstraint("organization_id", "actor_id", "submission_key", name="uq_board_portal_submission"),
    )
    op.create_index("ix_board_portal_organization_id", "board_portal", ["organization_id"])


def downgrade():
    op.drop_column("organizations", "customer_client_id")
    op.drop_index("ix_threads_meta_client_actor_id", table_name="threads_meta")
    op.drop_column("threads_meta", "client_actor_id")
    op.drop_table("board_portal")
    op.drop_column("board_messages", "attachments")
    op.drop_column("board_messages", "visibility")
