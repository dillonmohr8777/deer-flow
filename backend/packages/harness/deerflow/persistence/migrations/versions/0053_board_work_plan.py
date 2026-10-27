"""Staff-only recorded work planning on existing portal requests.

Revision ID: 0053_board_work_plan
Revises: 0052_board_portal
"""

import sqlalchemy as sa

revision = "0053_board_work_plan"
down_revision = "0052_board_portal"
branch_labels = depends_on = None


def upgrade():
    from deerflow.persistence.migrations._helpers import safe_add_column

    safe_add_column("board_portal", sa.Column("work_plan", sa.JSON(), nullable=True))
    safe_add_column("board_portal", sa.Column("work_plan_revision", sa.Integer(), nullable=False, server_default="0"))
    safe_add_column("board_portal", sa.Column("work_plan_updated_by_user_id", sa.String(64), nullable=True))
    safe_add_column("board_portal", sa.Column("work_plan_updated_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    from deerflow.persistence.migrations._helpers import safe_drop_column

    for name in ("work_plan_updated_at", "work_plan_updated_by_user_id", "work_plan_revision", "work_plan"):
        safe_drop_column("board_portal", name)
