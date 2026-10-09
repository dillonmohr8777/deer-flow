"""Migration tests for 0036_user_mfa.

Runs the full alembic chain on an empty SQLite database (not
``create_all`` + stamp), then exercises the 0035 downgrade/upgrade cycle.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from sqlalchemy.ext.asyncio import create_async_engine

from deerflow.persistence.bootstrap import _MIGRATIONS_DIR

pytestmark = pytest.mark.asyncio

_SCRIPT_LOCATION = str(_MIGRATIONS_DIR)
_PREVIOUS = "0035_fleet_agent_bindings"

_EXPECTED_COLUMNS = {
    "user_id",
    "secret_encrypted",
    "enabled_at",
    "recovery_codes",
    "created_at",
    "updated_at",
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


async def test_user_mfa_migration_upgrade_downgrade_cycle(tmp_path: Path) -> None:
    db_path = tmp_path / "user-mfa-migration.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    cfg = _alembic_config(f"sqlite+aiosqlite:///{db_path}")
    try:
        await asyncio.to_thread(alembic_command.upgrade, cfg, "head")

        tables = await _inspect(engine, _table_names)
        assert "user_mfa" in tables
        columns = await _inspect(engine, lambda conn: _column_names(conn, "user_mfa"))
        assert columns == _EXPECTED_COLUMNS

        # Downgrade to the previous revision drops exactly this table.
        await asyncio.to_thread(alembic_command.downgrade, cfg, _PREVIOUS)
        tables_after_down = await _inspect(engine, _table_names)
        assert "user_mfa" not in tables_after_down
        # clients (from 0034) survives the downgrade -- only 0035's own table drops.
        assert "clients" in tables_after_down

        # Upgrade again recreates it (idempotent round trip).
        await asyncio.to_thread(alembic_command.upgrade, cfg, "head")
        tables_after_up = await _inspect(engine, _table_names)
        assert "user_mfa" in tables_after_up
    finally:
        await engine.dispose()
