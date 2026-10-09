"""Migration tests for 0037_pat_organization.

Runs the full alembic chain on an empty SQLite database (not
``create_all`` + stamp), then exercises the 0036 downgrade/upgrade cycle
and the deterministic-private-organization backfill.
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from sqlalchemy.ext.asyncio import create_async_engine

from deerflow.persistence.bootstrap import _MIGRATIONS_DIR

pytestmark = pytest.mark.asyncio

_SCRIPT_LOCATION = str(_MIGRATIONS_DIR)
_PREVIOUS = "0036_user_mfa"


def _private_organization_id(user_id: str) -> str:
    return f"private-{hashlib.sha256(user_id.encode('utf-8')).hexdigest()[:48]}"


def _alembic_config(db_url: str) -> AlembicConfig:
    cfg = AlembicConfig()
    cfg.set_main_option("script_location", _SCRIPT_LOCATION)
    cfg.set_main_option("sqlalchemy.url", db_url.replace("%", "%%"))
    return cfg


def _table_names(sync_conn) -> set[str]:
    return set(sa.inspect(sync_conn).get_table_names())


def _column_names(sync_conn, table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(sync_conn).get_columns(table)}


def _index_names(sync_conn, table: str) -> set[str]:
    return {index["name"] for index in sa.inspect(sync_conn).get_indexes(table)}


async def _inspect(engine, fn):
    async with engine.connect() as conn:
        return await conn.run_sync(fn)


async def test_pat_organization_migration_upgrade_downgrade_cycle(tmp_path: Path) -> None:
    db_path = tmp_path / "pat-organization-migration.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    cfg = _alembic_config(f"sqlite+aiosqlite:///{db_path}")
    try:
        await asyncio.to_thread(alembic_command.upgrade, cfg, "head")

        columns = await _inspect(engine, lambda conn: _column_names(conn, "personal_access_tokens"))
        assert "organization_id" in columns
        indexes = await _inspect(engine, lambda conn: _index_names(conn, "personal_access_tokens"))
        assert "ix_personal_access_tokens_organization_id" in indexes

        # Downgrade to the previous revision drops exactly this column.
        await asyncio.to_thread(alembic_command.downgrade, cfg, _PREVIOUS)
        columns_after_down = await _inspect(engine, lambda conn: _column_names(conn, "personal_access_tokens"))
        assert "organization_id" not in columns_after_down
        # The table itself (from 0017) survives -- only this revision's column drops.
        tables_after_down = await _inspect(engine, _table_names)
        assert "personal_access_tokens" in tables_after_down
        # user_mfa (from 0036) survives too -- only this revision's own change drops.
        assert "user_mfa" in tables_after_down

        # Upgrade again recreates it (idempotent round trip).
        await asyncio.to_thread(alembic_command.upgrade, cfg, "head")
        columns_after_up = await _inspect(engine, lambda conn: _column_names(conn, "personal_access_tokens"))
        assert "organization_id" in columns_after_up
    finally:
        await engine.dispose()


async def test_pat_organization_backfill_stamps_owner_private_organization(tmp_path: Path) -> None:
    """A PAT minted before this migration is stamped to its owner's
    deterministic private organization -- the only organization any PAT
    could ever have acted in before 0037 (PAT auth never consulted the
    workspace-selection cookie). A token owned by a user with no matching
    active organization keeps NULL, the quarantine marker.
    """
    db_path = tmp_path / "pat-organization-backfill.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    cfg = _alembic_config(f"sqlite+aiosqlite:///{db_path}")
    try:
        # Land on 0036 (pre-0037) and seed rows by hand, exactly the shape a
        # live pre-migration database would have.
        await asyncio.to_thread(alembic_command.upgrade, cfg, _PREVIOUS)

        now = datetime.now(UTC)
        owned_user_id = "user-with-org"
        orphan_user_id = "user-without-org"
        owned_org_id = _private_organization_id(owned_user_id)
        owned_pat_id = str(uuid.uuid4())
        orphan_pat_id = str(uuid.uuid4())

        def _seed(sync_conn) -> None:
            sync_conn.execute(
                sa.text("INSERT INTO users (id, email, system_role, needs_setup, token_version, created_at) VALUES (:id, :email, 'user', 0, 0, :now)"),
                {"id": owned_user_id, "email": "owned@example.com", "now": now},
            )
            sync_conn.execute(
                sa.text("INSERT INTO users (id, email, system_role, needs_setup, token_version, created_at) VALUES (:id, :email, 'user', 0, 0, :now)"),
                {"id": orphan_user_id, "email": "orphan@example.com", "now": now},
            )
            sync_conn.execute(
                sa.text("INSERT INTO organizations (id, slug, name, status, created_at, updated_at) VALUES (:id, :slug, 'Private organization', 'active', :now, :now)"),
                {"id": owned_org_id, "slug": "owned-org", "now": now},
            )
            sync_conn.execute(
                sa.text("INSERT INTO organization_members (organization_id, user_id, role, status, created_at, updated_at) VALUES (:org, :user, 'owner', 'active', :now, :now)"),
                {"org": owned_org_id, "user": owned_user_id, "now": now},
            )
            # orphan_user_id gets no organizations row at all -- the backfill
            # must leave its PAT's organization_id NULL rather than guess.
            sync_conn.execute(
                sa.text("INSERT INTO personal_access_tokens (id, user_id, name, token_digest, scopes, created_at) VALUES (:id, :user_id, 'owned', :digest, '[\"runs:read\"]', :now)"),
                {"id": owned_pat_id, "user_id": owned_user_id, "digest": hashlib.sha256(b"owned-token").hexdigest(), "now": now},
            )
            sync_conn.execute(
                sa.text("INSERT INTO personal_access_tokens (id, user_id, name, token_digest, scopes, created_at) VALUES (:id, :user_id, 'orphan', :digest, '[\"runs:read\"]', :now)"),
                {"id": orphan_pat_id, "user_id": orphan_user_id, "digest": hashlib.sha256(b"orphan-token").hexdigest(), "now": now},
            )

        async with engine.begin() as conn:
            await conn.run_sync(_seed)

        await asyncio.to_thread(alembic_command.upgrade, cfg, "head")

        def _read_org(sync_conn, pat_id: str) -> str | None:
            return sync_conn.execute(sa.text("SELECT organization_id FROM personal_access_tokens WHERE id = :id"), {"id": pat_id}).scalar_one()

        owned_org = await _inspect(engine, lambda conn: _read_org(conn, owned_pat_id))
        orphan_org = await _inspect(engine, lambda conn: _read_org(conn, orphan_pat_id))
        assert owned_org == owned_org_id
        assert orphan_org is None
    finally:
        await engine.dispose()
