"""Opt-in client portal; existing messages remain internal.

Revision ID: 0052_board_portal
Revises: 0051_client_corrections

Every step is guarded: a database bootstrapped by ``create_all`` already has the
new columns and table, and re-adding them would fail the upgrade.
"""

import sqlalchemy as sa
from alembic import op

revision = "0052_board_portal"
down_revision = "0051_client_corrections"
branch_labels = depends_on = None

_COLUMNS = (
    ("organizations", lambda: sa.Column("customer_client_id", sa.String(64), nullable=True)),
    ("threads_meta", lambda: sa.Column("client_actor_id", sa.String(64), nullable=True)),
    ("board_messages", lambda: sa.Column("visibility", sa.String(16), nullable=False, server_default="internal")),
    ("board_messages", lambda: sa.Column("attachments", sa.JSON(), nullable=True)),
)


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade():
    for table, column in _COLUMNS:
        col = column()
        if col.name not in _columns(table):
            op.add_column(table, col)
    if "ix_threads_meta_client_actor_id" not in _indexes("threads_meta"):
        op.create_index("ix_threads_meta_client_actor_id", "threads_meta", ["client_actor_id"])
    if "board_portal" not in sa.inspect(op.get_bind()).get_table_names():
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
    if "ix_board_portal_organization_id" not in _indexes("board_portal"):
        op.create_index("ix_board_portal_organization_id", "board_portal", ["organization_id"])


def downgrade():
    if "board_portal" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("board_portal")
    if "ix_threads_meta_client_actor_id" in _indexes("threads_meta"):
        op.drop_index("ix_threads_meta_client_actor_id", table_name="threads_meta")
    for table, column in reversed(_COLUMNS):
        name = column().name
        if name in _columns(table):
            op.drop_column(table, name)
