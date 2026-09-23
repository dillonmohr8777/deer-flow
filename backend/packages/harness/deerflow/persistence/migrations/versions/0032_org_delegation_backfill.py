"""Grant organization delegations to existing internal callers; data only.

Revision ID: 0032_org_delegation_backfill
Revises: 0031_org_rebackfill

Phase 2 of the M3 gate refuses every internal call that does not present an
active delegation, so the internal subjects that already exist get one here,
in the same deploy:

- ``scheduled_task``: every organization-stamped task (scope ``runs:create``);
- ``mcp_task``: every organization-stamped MCP task (scope ``runs:create``,
  for its notification runs);
- ``channel_connection``: every ``connected`` organization-stamped connection
  (the channel worker scopes).

The owner must be an active member of the active organization: the row's own
user when it is one, otherwise (a shared workspace's storage principal is never
a member) the organization's single active ``owner``. A row with no such owner,
a NULL organization (quarantine) or an existing active delegation is skipped
and counted in the log; it fails closed until someone re-grants it.

Ids are deterministic (``dlg0032-`` plus a digest), so the upgrade is
idempotent and the downgrade deletes exactly what it created. Scope lists are
duplicated from runtime code on purpose, as in 0027.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "0032_org_delegation_backfill"
down_revision: str | Sequence[str] | None = "0031_org_rebackfill"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger(__name__)

_ID_PREFIX = "dlg0032-"
_RUNS_CREATE = ["runs:create"]
_CHANNEL_WORKER_SCOPES = ["runs:create", "runs:read", "threads:read", "threads:write"]

# (subject type, table, owner column, extra WHERE, scopes)
_SUBJECTS = (
    ("scheduled_task", "scheduled_tasks", "user_id", "", _RUNS_CREATE),
    ("mcp_task", "mcp_tasks", "user_id", "", _RUNS_CREATE),
    ("channel_connection", "channel_connections", "owner_user_id", " AND status = 'connected'", _CHANNEL_WORKER_SCOPES),
)

_delegations = sa.table(
    "organization_delegations",
    sa.column("id", sa.String),
    sa.column("organization_id", sa.String),
    sa.column("subject_type", sa.String),
    sa.column("subject_id", sa.String),
    sa.column("owner_user_id", sa.String),
    sa.column("scopes", sa.JSON),
    sa.column("status", sa.String),
    sa.column("expires_at", sa.DateTime(timezone=True)),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("updated_at", sa.DateTime(timezone=True)),
)


def _delegation_id(subject_type: str, subject_id: str, organization_id: str) -> str:
    return _ID_PREFIX + hashlib.sha256(f"{subject_type}\0{subject_id}\0{organization_id}".encode()).hexdigest()[:48]


def _has_table(bind, table: str) -> bool:
    return sa.inspect(bind).has_table(table)


def upgrade() -> None:
    bind = op.get_bind()
    if not all(_has_table(bind, table) for table in ("organizations", "organization_members", "organization_delegations")):
        return

    active_members: dict[str, dict[str, str]] = {}
    for organization_id, user_id, role in bind.execute(sa.text("SELECT m.organization_id, m.user_id, m.role FROM organization_members m JOIN organizations o ON o.id = m.organization_id WHERE m.status = 'active' AND o.status = 'active'")):
        active_members.setdefault(str(organization_id), {})[str(user_id)] = str(role)
    active = bind.execute(sa.text("SELECT subject_type, subject_id, organization_id FROM organization_delegations WHERE status = 'active'"))
    delegated = {(str(subject_type), str(subject_id), str(organization_id)) for subject_type, subject_id, organization_id in active}

    def owner_for(organization_id: str, user_id: str | None) -> str | None:
        members = active_members.get(organization_id, {})
        if user_id is not None and user_id in members:
            return user_id
        owners = [member for member, role in members.items() if role == "owner"]
        return owners[0] if len(owners) == 1 else None

    now = datetime.now(UTC)
    rows = []
    for subject_type, table, owner_column, extra, scopes in _SUBJECTS:
        if not _has_table(bind, table):
            continue
        skipped = 0
        for subject_id, owner_id, organization_id in bind.execute(sa.text(f"SELECT id, {owner_column}, organization_id FROM {table} WHERE organization_id IS NOT NULL{extra}")):
            subject_id, organization_id = str(subject_id), str(organization_id)
            if (subject_type, subject_id, organization_id) in delegated:
                continue
            owner = owner_for(organization_id, str(owner_id) if owner_id is not None else None)
            if owner is None:
                skipped += 1
                continue
            rows.append(
                {
                    "id": _delegation_id(subject_type, subject_id, organization_id),
                    "organization_id": organization_id,
                    "subject_type": subject_type,
                    "subject_id": subject_id,
                    "owner_user_id": owner,
                    "scopes": scopes,
                    "status": "active",
                    "expires_at": None,
                    "created_at": now,
                    "updated_at": now,
                }
            )
        if skipped:
            logger.warning("%s: %d %s row(s) have no active owner to delegate to and stay undelegated", revision, skipped, table)
    if rows:
        op.bulk_insert(_delegations, rows)


def downgrade() -> None:
    bind = op.get_bind()
    if _has_table(bind, "organization_delegations"):
        bind.execute(sa.text("DELETE FROM organization_delegations WHERE id LIKE :prefix"), {"prefix": _ID_PREFIX + "%"})
