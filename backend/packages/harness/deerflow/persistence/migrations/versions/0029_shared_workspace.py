"""Add shared-workspace storage principals and invitation metadata.

Revision ID: 0029_shared_workspace
Revises: 0028_merge_org_mcp

``storage_user_id`` is nullable by design: existing private organizations
continue to use their owner as the storage principal, while a shared
workspace opts into one explicit non-login storage principal. Invitation rows
are metadata only; membership activation remains the invitation consumer's
transactional responsibility.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0029_shared_workspace"
down_revision: str | Sequence[str] | None = "0028_merge_org_mcp"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table)


def _indexes(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table):
        return set()
    return {index["name"] for index in inspector.get_indexes(table)}


def _safe_create_index(name: str, table: str, columns: list[str], *, unique: bool = False) -> None:
    if name not in _indexes(table):
        op.create_index(name, table, columns, unique=unique)


def _safe_drop_index(name: str, table: str) -> None:
    if name in _indexes(table):
        op.drop_index(name, table_name=table)


def upgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_add_column

    safe_add_column("organizations", sa.Column("storage_user_id", sa.String(length=64), nullable=True))
    _safe_create_index("ix_organizations_storage_user_id", "organizations", ["storage_user_id"])

    if not _has_table("workspace_invitations"):
        op.create_table(
            "workspace_invitations",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("organization_id", sa.String(length=64), nullable=False),
            sa.Column("email", sa.String(length=320), nullable=False),
            sa.Column("role", sa.String(length=32), nullable=False),
            sa.Column("created_by", sa.String(length=64), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("token_hash", name="uq_workspace_invitations_token_hash"),
        )
    _safe_create_index("ix_workspace_invitations_token_hash", "workspace_invitations", ["token_hash"])
    _safe_create_index("ix_workspace_invitations_organization_id", "workspace_invitations", ["organization_id"])
    _safe_create_index("ix_workspace_invitations_email", "workspace_invitations", ["email"])


def downgrade() -> None:
    _safe_drop_index("ix_workspace_invitations_email", "workspace_invitations")
    _safe_drop_index("ix_workspace_invitations_organization_id", "workspace_invitations")
    _safe_drop_index("ix_workspace_invitations_token_hash", "workspace_invitations")
    if _has_table("workspace_invitations"):
        op.drop_table("workspace_invitations")

    _safe_drop_index("ix_organizations_storage_user_id", "organizations")
    from deerflow.persistence.migrations._helpers import safe_drop_column

    safe_drop_column("organizations", "storage_user_id")
