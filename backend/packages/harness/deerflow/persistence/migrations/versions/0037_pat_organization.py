"""personal_access_tokens.organization_id.

Revision ID: 0037_pat_organization
Revises: 0036_user_mfa

M3 gap: PATs carried no ``organization_id`` (`AGENTS.md` "Organization
isolation (M3)"), so PAT-authenticated requests always resolved to the
owner's private organization regardless of which organization was active
when the token was minted -- PAT auth never consulted the workspace-
selection cookie. Adds a nullable, indexed ``organization_id`` column,
matching every other organization-scoped table, and backfills existing
rows to their owner's deterministic private organization -- the only
organization any PAT could ever have acted in before this revision. The
backfill mirrors 0031_org_rebackfill: it only stamps into an
already-active organization naming that user (or no one) as storage
principal, and creates no organization or membership. A row whose owner
has no such organization keeps NULL, the quarantine marker used
throughout the organization-isolation rollout.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0037_pat_organization"
down_revision: str | Sequence[str] | None = "0036_user_mfa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _private_organization_id(user_id: str) -> str:
    return f"private-{hashlib.sha256(user_id.encode('utf-8')).hexdigest()[:48]}"


def _has_table(bind, table: str) -> bool:
    return sa.inspect(bind).has_table(table)


def upgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_add_column

    bind = op.get_bind()
    safe_add_column("personal_access_tokens", sa.Column("organization_id", sa.String(length=64), nullable=True))

    inspector = sa.inspect(bind)
    if inspector.has_table("personal_access_tokens"):
        existing_indexes = {i["name"] for i in inspector.get_indexes("personal_access_tokens")}
        if "ix_personal_access_tokens_organization_id" not in existing_indexes:
            op.create_index("ix_personal_access_tokens_organization_id", "personal_access_tokens", ["organization_id"])

    if not _has_table(bind, "personal_access_tokens") or not _has_table(bind, "users") or not _has_table(bind, "organizations"):
        return

    # Mirrors 0031_org_rebackfill: stamp only into an organization that
    # already exists, is active, and names the owner (or no one) as its
    # storage principal. Creates no organization or membership.
    organizations = {str(organization_id): storage_user_id for organization_id, storage_user_id in bind.execute(sa.text("SELECT id, storage_user_id FROM organizations WHERE status = 'active'"))}
    users: dict[str, str] = {}
    for (user_id,) in bind.execute(sa.text("SELECT id FROM users WHERE id IS NOT NULL")):
        user_id = str(user_id)
        organization_id = _private_organization_id(user_id)
        if organization_id in organizations and organizations[organization_id] in (None, user_id):
            users[user_id] = organization_id

    for pat_id, owner_id in bind.execute(sa.text("SELECT id, user_id FROM personal_access_tokens WHERE organization_id IS NULL")):
        organization_id = users.get(str(owner_id)) if owner_id is not None else None
        if organization_id is not None:
            bind.execute(
                sa.text("UPDATE personal_access_tokens SET organization_id = :organization_id WHERE id = :id AND organization_id IS NULL"),
                {"organization_id": organization_id, "id": pat_id},
            )


def downgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_drop_column

    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("personal_access_tokens"):
        existing_indexes = {i["name"] for i in inspector.get_indexes("personal_access_tokens")}
        if "ix_personal_access_tokens_organization_id" in existing_indexes:
            op.drop_index("ix_personal_access_tokens_organization_id", table_name="personal_access_tokens")
    safe_drop_column("personal_access_tokens", "organization_id")
