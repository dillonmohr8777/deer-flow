"""fleet_agent_bindings: idempotent template-to-client agent stamps.

Revision ID: 0035_fleet_agent_bindings
Revises: 0034_clients

Fleet foundation item 3 (client binding). ``POST /api/clients/{client_id}/agents``
stamps a fleet template into a real custom agent for one client. Custom agents
are stored per-user (``agents`` table, JSON ``config`` document — see
``deerflow.persistence.agents.model``), so this table is the organization-scoped
index that answers "which agent did we already stamp for (client, template)"
without ever calling ``AgentStore.list_all()`` from an org-scoped route (that
cross-owner scan is reserved for the GitHub registry; see
``persistence/agents/sql.py``). The unique constraint on
``(client_id, template_id)`` is the idempotency guarantee: stamping the same
template twice for one client can only ever produce one row.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0035_fleet_agent_bindings"
down_revision: str | Sequence[str] | None = "0034_clients"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("fleet_agent_bindings"):
        op.create_table(
            "fleet_agent_bindings",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("organization_id", sa.String(length=64), nullable=True),
            sa.Column("client_id", sa.String(length=64), nullable=False),
            sa.Column("template_id", sa.String(length=128), nullable=False),
            sa.Column("template_version", sa.String(length=32), nullable=False),
            sa.Column("agent_name", sa.String(length=128), nullable=False),
            sa.Column("agent_owner_user_id", sa.String(length=64), nullable=False),
            sa.Column("scheduled_task_id", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("client_id", "template_id", name="uq_fleet_agent_bindings_client_template"),
        )
        op.create_index("ix_fleet_agent_bindings_organization_id", "fleet_agent_bindings", ["organization_id"])
        op.create_index("ix_fleet_agent_bindings_client_id", "fleet_agent_bindings", ["client_id"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("fleet_agent_bindings"):
        op.drop_index("ix_fleet_agent_bindings_client_id", table_name="fleet_agent_bindings")
        op.drop_index("ix_fleet_agent_bindings_organization_id", table_name="fleet_agent_bindings")
        op.drop_table("fleet_agent_bindings")
