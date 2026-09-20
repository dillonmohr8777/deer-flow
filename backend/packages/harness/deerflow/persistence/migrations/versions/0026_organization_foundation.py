"""Add nullable organization identity schema without activating tenant behavior.

Revision ID: 0026_organization_foundation
Revises: 0025_repair_run_change_seq
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026_organization_foundation"
down_revision: str | Sequence[str] | None = "0025_repair_run_change_seq"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RESOURCE_TABLES = (
    "agents",
    "projects",
    "project_documents",
    "threads_meta",
    "runs",
    "scheduled_tasks",
    "scheduled_task_runs",
    "subagent_batches",
    "channel_connections",
    "channel_oauth_states",
    "channel_conversations",
    "mcp_tasks",
    "feedback",
)


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

    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("organizations"):
        op.create_table(
            "organizations",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("slug", sa.String(length=128), nullable=False),
            sa.Column("name", sa.String(length=256), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
    _safe_create_index("ix_organizations_slug", "organizations", ["slug"], unique=True)

    if not inspector.has_table("organization_members"):
        op.create_table(
            "organization_members",
            sa.Column("organization_id", sa.String(length=64), nullable=False),
            sa.Column("user_id", sa.String(length=64), nullable=False),
            sa.Column("role", sa.String(length=32), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("organization_id", "user_id"),
        )
    _safe_create_index("ix_organization_members_user_id", "organization_members", ["user_id"])
    _safe_create_index("ix_organization_members_status", "organization_members", ["status"])

    if not inspector.has_table("organization_delegations"):
        op.create_table(
            "organization_delegations",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("organization_id", sa.String(length=64), nullable=False),
            sa.Column("subject_type", sa.String(length=32), nullable=False),
            sa.Column("subject_id", sa.String(length=128), nullable=False),
            sa.Column("owner_user_id", sa.String(length=64), nullable=False),
            sa.Column("scopes", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
    _safe_create_index(
        "ix_organization_delegations_subject",
        "organization_delegations",
        ["organization_id", "subject_type", "subject_id"],
    )

    for table in _RESOURCE_TABLES:
        safe_add_column(table, sa.Column("organization_id", sa.String(length=64), nullable=True))
        _safe_create_index(f"ix_{table}_organization_id", table, ["organization_id"])


def downgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_drop_column

    for table in _RESOURCE_TABLES:
        _safe_drop_index(f"ix_{table}_organization_id", table)
        safe_drop_column(table, "organization_id")

    for table, indexes in (
        ("organization_delegations", ("ix_organization_delegations_subject",)),
        ("organization_members", ("ix_organization_members_status", "ix_organization_members_user_id")),
        ("organizations", ("ix_organizations_slug",)),
    ):
        for name in indexes:
            _safe_drop_index(name, table)
        if sa.inspect(op.get_bind()).has_table(table):
            op.drop_table(table)
