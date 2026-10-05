"""Repair an absent audit table in databases already stamped beyond 0033.

Revision ID: 0048_repair_audit_events
Revises: 0047_merge_agent_room_exec

Older empty-database bootstrap could stamp head before AuditEventRow was
registered. Registering it now repairs fresh databases, but managed databases
only walk forward and never replay 0033. Reapply its immutable audit-table DDL
without touching users or other tables. Existing incompatible shapes fail
closed instead of being silently stamped. Downgrade retains append-only history:
the audit schema belongs to ancestor 0033, whose downgrade owns its removal.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0048_repair_audit_events"
down_revision: str | Sequence[str] | None = "0047_merge_agent_room_exec"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns() -> list[sa.Column]:
    # Freeze the shipped 0033 shape; do not import mutable application models.
    return [
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
    ]


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = _columns()
    if not inspector.has_table("audit_events"):
        op.create_table("audit_events", *columns, sa.PrimaryKeyConstraint("id"))
        inspector = sa.inspect(op.get_bind())
    else:
        actual = {column["name"]: column for column in inspector.get_columns("audit_events")}
        compatible = set(actual) == {column.name for column in columns}
        for column in columns:
            existing = actual.get(column.name)
            compatible = compatible and existing is not None
            if existing is not None:
                compatible = compatible and isinstance(existing["type"], type(column.type)) and existing["nullable"] == column.nullable and existing.get("default") is None
                if isinstance(column.type, sa.String):
                    compatible = compatible and isinstance(existing["type"], sa.String) and existing["type"].length == column.type.length
                if isinstance(column.type, sa.DateTime) and op.get_bind().dialect.name == "postgresql":
                    # SQLite does not reflect timezone; PostgreSQL does.
                    compatible = compatible and isinstance(existing["type"], sa.DateTime) and existing["type"].timezone == column.type.timezone
        compatible = (
            compatible
            and inspector.get_pk_constraint("audit_events")["constrained_columns"] == ["id"]
            and not inspector.get_foreign_keys("audit_events")
            and not inspector.get_unique_constraints("audit_events")
            and not inspector.get_check_constraints("audit_events")
        )
        if not compatible:
            raise RuntimeError("audit_events has incompatible existing table schema; refusing repair")
    indexes = {index["name"]: index for index in inspector.get_indexes("audit_events")}
    required = {"ix_audit_events_occurred_at": "occurred_at", "ix_audit_events_action": "action", "ix_audit_events_organization_id": "organization_id", "ix_audit_events_actor_user_id": "actor_user_id"}
    if set(indexes) - set(required):
        raise RuntimeError("audit_events has incompatible unexpected index schema; refusing repair")
    # Validate every existing named index before adding any missing one.
    for name, column in required.items():
        existing = indexes.get(name)
        if existing is not None and (existing["column_names"] != [column] or existing["unique"] or any(existing.get("dialect_options", {}).values())):
            raise RuntimeError("audit_events has incompatible existing index schema; refusing repair")
    for name, column in required.items():
        if name not in indexes:
            op.create_index(name, "audit_events", [column])


def downgrade() -> None:
    # Ancestor 0033 owns this schema; never discard append-only history here.
    return None
