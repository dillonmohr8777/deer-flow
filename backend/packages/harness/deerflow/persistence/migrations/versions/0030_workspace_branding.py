"""Add shared-workspace branding.

Revision ID: 0030_workspace_branding
Revises: 0029_shared_workspace

A 1:1 side table keyed by ``organizations.id``. It is deliberately not columns
on ``organizations``: that row is selected on every authenticated request by
``active_organization_for_user()``, and a bounded logo column would be read on
the hot auth path every time.

Additive and reversible. No existing row is read, rewritten or backfilled, so
private organizations and the shared-workspace overlay are untouched.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0030_workspace_branding"
down_revision: str | Sequence[str] | None = "0029_shared_workspace"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "organization_branding"


def _has_table(table: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table)


def upgrade() -> None:
    if _has_table(_TABLE):
        return
    op.create_table(
        _TABLE,
        sa.Column("organization_id", sa.String(length=64), primary_key=True),
        sa.Column("brand_name", sa.String(length=120), nullable=True),
        sa.Column("logo_data_uri", sa.Text(), nullable=True),
        sa.Column("treatment", sa.String(length=16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    if _has_table(_TABLE):
        op.drop_table(_TABLE)
