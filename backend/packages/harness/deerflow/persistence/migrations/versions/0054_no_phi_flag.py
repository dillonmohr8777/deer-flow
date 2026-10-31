"""No-PHI flag on organizations and clients.

Revision ID: 0054_no_phi_flag
Revises: 0053_board_work_plan

Health-sector clients get a server-owned ``no_phi`` boolean. A workspace is
no-PHI when its own flag is set or the canonical client it is bound to has the
flag set. Additive, NOT NULL with a false server default, so a binary that
predates the column keeps inserting rows that read as not flagged. Plain
``op.add_column`` / ``op.drop_column`` (as in 0052) keep SQLite on cheap ALTERs
instead of a batch table rebuild.
"""

import sqlalchemy as sa
from alembic import op

revision = "0054_no_phi_flag"
down_revision = "0053_board_work_plan"
branch_labels = depends_on = None

_TABLES = ("organizations", "clients")


def _columns(table: str) -> set[str] | None:
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return None
    return {c["name"] for c in inspector.get_columns(table)}


def upgrade():
    for table in _TABLES:
        columns = _columns(table)
        if columns is not None and "no_phi" not in columns:
            op.add_column(table, sa.Column("no_phi", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    for table in reversed(_TABLES):
        columns = _columns(table)
        if columns is not None and "no_phi" in columns:
            op.drop_column(table, "no_phi")
