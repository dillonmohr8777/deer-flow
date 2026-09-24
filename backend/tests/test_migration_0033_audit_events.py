"""Migration tests for 0033_audit_events.

Runs the full alembic chain on an empty SQLite database (not
``create_all`` + stamp), then exercises the 0033 downgrade/upgrade cycle for
both the new ``audit_events`` table and the ``users.disabled_at`` column.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import create_async_engine

from deerflow.persistence.bootstrap import _MIGRATIONS_DIR

pytestmark = pytest.mark.asyncio

_SCRIPT_LOCATION = str(_MIGRATIONS_DIR)
_REVISION = "0033_audit_events"
_PREVIOUS = "0032_org_delegation_backfill"

_EXPECTED_COLUMNS = {
    "id",
    "occurred_at",
    "actor_user_id",
    "organization_id",
    "action",
    "target_type",
    "target_id",
    "outcome",
    "ip",
    "user_agent",
    "details",
}


def _alembic_config(db_url: str) -> AlembicConfig:
    cfg = AlembicConfig()
    cfg.set_main_option("script_location", _SCRIPT_LOCATION)
    cfg.set_main_option("sqlalchemy.url", db_url.replace("%", "%%"))
    return cfg


def _table_names(sync_conn) -> set[str]:
    return set(sa.inspect(sync_conn).get_table_names())


def _column_names(sync_conn, table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(sync_conn).get_columns(table)}


async def _inspect(engine, fn):
    async with engine.connect() as conn:
        return await conn.run_sync(fn)


async def test_audit_events_migration_upgrade_downgrade_cycle(tmp_path: Path) -> None:
    db_path = tmp_path / "audit-events-migration.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    cfg = _alembic_config(f"sqlite+aiosqlite:///{db_path}")
    try:
        await asyncio.to_thread(alembic_command.upgrade, cfg, "head")

        tables = await _inspect(engine, _table_names)
        assert "audit_events" in tables
        columns = await _inspect(engine, lambda conn: _column_names(conn, "audit_events"))
        assert columns == _EXPECTED_COLUMNS
        indexes = await _inspect(engine, lambda conn: {idx["name"] for idx in sa.inspect(conn).get_indexes("audit_events")})
        assert "ix_audit_events_occurred_at" in indexes
        assert "ix_audit_events_action" in indexes
        assert "ix_audit_events_organization_id" in indexes
        assert "ix_audit_events_actor_user_id" in indexes

        user_columns = await _inspect(engine, lambda conn: _column_names(conn, "users"))
        assert "disabled_at" in user_columns

        # Downgrade to the previous revision drops the table and the column.
        await asyncio.to_thread(alembic_command.downgrade, cfg, _PREVIOUS)
        tables_after_down = await _inspect(engine, _table_names)
        assert "audit_events" not in tables_after_down
        user_columns_after_down = await _inspect(engine, lambda conn: _column_names(conn, "users"))
        assert "disabled_at" not in user_columns_after_down

        # Upgrade again recreates both (idempotent round trip).
        await asyncio.to_thread(alembic_command.upgrade, cfg, "head")
        tables_after_up = await _inspect(engine, _table_names)
        assert "audit_events" in tables_after_up
        user_columns_after_up = await _inspect(engine, lambda conn: _column_names(conn, "users"))
        assert "disabled_at" in user_columns_after_up
    finally:
        await engine.dispose()


async def test_audit_events_chains_into_the_single_head(tmp_path: Path) -> None:
    """Upgrading to head passes through 0033 and lands on the one head (0034+ chain on top)."""
    script = ScriptDirectory(str(_MIGRATIONS_DIR))
    heads = script.get_heads()
    assert len(heads) == 1
    assert _REVISION in {rev.revision for rev in script.walk_revisions(base=_PREVIOUS, head=heads[0])}
    db_path = tmp_path / "audit-events-head.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    cfg = _alembic_config(f"sqlite+aiosqlite:///{db_path}")
    try:
        await asyncio.to_thread(alembic_command.upgrade, cfg, "head")

        async with engine.connect() as conn:
            version = await conn.run_sync(lambda sync: sync.execute(sa.text("SELECT version_num FROM alembic_version")).scalar())
        assert version == heads[0]
    finally:
        await engine.dispose()
