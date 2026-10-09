"""Append-only audit log plus admin user-disable support.

Revision ID: 0033_audit_events
Revises: 0032_org_delegation_backfill
Create Date: 2026-09-23

SOC 2 style controls (Phase 1 of the client-readiness plan). Another lane is
adding 0034 in parallel off the same 0032 head; the lead chains them at merge.

Adds:

- ``audit_events``: append-only security and admin action log. ``details``
  is a JSON blob that must never carry secrets -- the repository
  (``deerflow.persistence.audit_events.AuditEventRepository.record``)
  redacts before every insert via
  ``deerflow.persistence.audit_events.redact_audit_details``; this migration
  only shapes the column.
- ``users.disabled_at``: set by ``POST /api/admin/users/{id}/disable``. A
  disabled user cannot log in and its existing sessions stop validating
  (checked in ``get_current_user_from_request``).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0033_audit_events"
down_revision: str | Sequence[str] | None = "0032_org_delegation_backfill"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_add_column

    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("audit_events"):
        op.create_table(
            "audit_events",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("actor_user_id", sa.String(length=64), nullable=True),
            sa.Column("organization_id", sa.String(length=64), nullable=True),
            sa.Column("action", sa.String(length=128), nullable=False),
            sa.Column("target_type", sa.String(length=64), nullable=True),
            sa.Column("target_id", sa.String(length=128), nullable=True),
            sa.Column("outcome", sa.String(length=16), nullable=False),
            sa.Column("ip", sa.String(length=64), nullable=True),
            sa.Column("user_agent", sa.String(length=256), nullable=True),
            sa.Column("details", sa.JSON(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_audit_events_occurred_at", "audit_events", ["occurred_at"])
        op.create_index("ix_audit_events_action", "audit_events", ["action"])
        op.create_index("ix_audit_events_organization_id", "audit_events", ["organization_id"])
        op.create_index("ix_audit_events_actor_user_id", "audit_events", ["actor_user_id"])

    safe_add_column("users", sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_drop_column

    safe_drop_column("users", "disabled_at")

    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("audit_events"):
        op.drop_index("ix_audit_events_actor_user_id", table_name="audit_events")
        op.drop_index("ix_audit_events_organization_id", table_name="audit_events")
        op.drop_index("ix_audit_events_action", table_name="audit_events")
        op.drop_index("ix_audit_events_occurred_at", table_name="audit_events")
        op.drop_table("audit_events")
