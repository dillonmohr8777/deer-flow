"""clients, client_assignments, projects.client_id.

Revision ID: 0034_clients
Revises: 0033_audit_events

Momentum Phase 2 item 2: an organization-scoped client roster (not user-owned:
``clients`` carries no ``user_id``, matching ``organizations`` itself)
plus per-user assignments. ``registry_id`` is unique per organization (NULLs
stay distinct under a plain composite unique constraint on both SQLite and
Postgres), so the registry importer (item 3) can upsert idempotently.
``client_assignments`` mirrors ``organization_members``: a composite primary
key enforces "unique per client+user" without a synthetic id column.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0034_clients"
down_revision: str | Sequence[str] | None = "0033_audit_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_add_column

    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("clients"):
        op.create_table(
            "clients",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("organization_id", sa.String(length=64), nullable=True),
            sa.Column("display_name", sa.String(length=255), nullable=False),
            sa.Column("aliases", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("email_domains", sa.JSON(), nullable=False),
            sa.Column("slack_channel_ids", sa.JSON(), nullable=False),
            sa.Column("registry_id", sa.String(length=128), nullable=True),
            sa.Column("notes", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("organization_id", "registry_id", name="uq_clients_org_registry_id"),
        )
        op.create_index("ix_clients_organization_id", "clients", ["organization_id"])
        op.create_index("ix_clients_status", "clients", ["status"])
        op.create_index("ix_clients_registry_id", "clients", ["registry_id"])

    if not inspector.has_table("client_assignments"):
        op.create_table(
            "client_assignments",
            sa.Column("client_id", sa.String(length=64), nullable=False),
            sa.Column("user_id", sa.String(length=64), nullable=False),
            sa.Column("organization_id", sa.String(length=64), nullable=True),
            sa.Column("role", sa.String(length=32), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("client_id", "user_id"),
        )
        op.create_index("ix_client_assignments_user_id", "client_assignments", ["user_id"])
        op.create_index("ix_client_assignments_organization_id", "client_assignments", ["organization_id"])

    safe_add_column("projects", sa.Column("client_id", sa.String(length=64), nullable=True))
    existing = {i["name"] for i in inspector.get_indexes("projects")}
    if "ix_projects_client_id" not in existing:
        op.create_index("ix_projects_client_id", "projects", ["client_id"])


def downgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_drop_column

    inspector = sa.inspect(op.get_bind())
    existing = {i["name"] for i in inspector.get_indexes("projects")}
    if "ix_projects_client_id" in existing:
        op.drop_index("ix_projects_client_id", table_name="projects")
    safe_drop_column("projects", "client_id")

    if inspector.has_table("client_assignments"):
        op.drop_index("ix_client_assignments_organization_id", table_name="client_assignments")
        op.drop_index("ix_client_assignments_user_id", table_name="client_assignments")
        op.drop_table("client_assignments")

    if inspector.has_table("clients"):
        op.drop_index("ix_clients_registry_id", table_name="clients")
        op.drop_index("ix_clients_status", table_name="clients")
        op.drop_index("ix_clients_organization_id", table_name="clients")
        op.drop_table("clients")
