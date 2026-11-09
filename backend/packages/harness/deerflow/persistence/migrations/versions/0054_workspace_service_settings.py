"""Add per-workspace service settings (service tier, seller, booking link, onboarding plan).

Revision ID: 0054_workspace_service_settings
Revises: 0053_board_work_plan

A 1:1 side table keyed by ``organizations.id``, like ``organization_branding``.
Additive and reversible: no existing row is read, rewritten or backfilled, so
every existing workspace has no tier and keeps its current review routing. The
application never reads this table while ``service_tiers.enabled`` is false.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0054_workspace_service_settings"
down_revision: str | Sequence[str] | None = "0053_board_work_plan"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "workspace_service_settings"


def _has_table(table: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table)


def upgrade() -> None:
    if _has_table(_TABLE):
        return
    op.create_table(
        _TABLE,
        sa.Column("organization_id", sa.String(length=64), primary_key=True),
        sa.Column("service_tier", sa.String(length=16), nullable=True),
        sa.Column("sold_by_user_id", sa.String(length=64), nullable=True),
        sa.Column("booking_url", sa.String(length=512), nullable=True),
        sa.Column("check_in_task_id", sa.String(length=64), nullable=True),
        sa.Column("onboarding", sa.JSON(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    if _has_table(_TABLE):
        op.drop_table(_TABLE)
