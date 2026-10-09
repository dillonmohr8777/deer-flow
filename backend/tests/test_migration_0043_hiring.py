"""Migration tests for 0043_hiring.

Runs the full alembic chain on an empty SQLite database (not ``create_all`` +
stamp), then exercises the 0043 downgrade/upgrade cycle for both the new
``hired_agents`` table and the ``agent_seats.model_family`` column. Queue item
f110(c): the review round on PR #92 (e12 agent-hiring) named this migration's
own round-trip test as left open.
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
_REVISION = "0043_hiring"
_PREVIOUS = "0042_agent_seats_scorecard"

_EXPECTED_COLUMNS = {
    "id",
    "organization_id",
    "agent_name",
    "title",
    "manager_agent_name",
    "job",
    "kpi",
    "model_family",
    "tool_groups",
    "private_data",
    "weekly_token_budget",
    "depth",
    "status",
    "hired_by_user_id",
    "retired_by_user_id",
    "created_at",
    "updated_at",
    "retired_at",
    "missed_kpi_checks",
    "last_kpi_check_at",
}

_EXPECTED_INDEXES = {
    "ix_hired_agents_organization_id",
    "ix_hired_agents_agent_name",
    "ix_hired_agents_manager_agent_name",
    "ix_hired_agents_status",
    "ix_hired_agents_org_manager",
    "uq_hired_agents_active_agent_name",
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


def _index_names(sync_conn, table: str) -> set[str]:
    return {idx["name"] for idx in sa.inspect(sync_conn).get_indexes(table)}


async def _inspect(engine, fn):
    async with engine.connect() as conn:
        return await conn.run_sync(fn)


async def test_hiring_migration_upgrade_downgrade_cycle(tmp_path: Path) -> None:
    db_path = tmp_path / "hiring-migration.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    cfg = _alembic_config(f"sqlite+aiosqlite:///{db_path}")
    try:
        await asyncio.to_thread(alembic_command.upgrade, cfg, "head")

        tables = await _inspect(engine, _table_names)
        assert "hired_agents" in tables
        columns = await _inspect(engine, lambda conn: _column_names(conn, "hired_agents"))
        assert columns == _EXPECTED_COLUMNS
        indexes = await _inspect(engine, lambda conn: _index_names(conn, "hired_agents"))
        assert _EXPECTED_INDEXES <= indexes

        seat_columns = await _inspect(engine, lambda conn: _column_names(conn, "agent_seats"))
        assert "model_family" in seat_columns

        # Downgrade to the previous revision drops the table and the column.
        await asyncio.to_thread(alembic_command.downgrade, cfg, _PREVIOUS)
        tables_after_down = await _inspect(engine, _table_names)
        assert "hired_agents" not in tables_after_down
        seat_columns_after_down = await _inspect(engine, lambda conn: _column_names(conn, "agent_seats"))
        assert "model_family" not in seat_columns_after_down

        # Upgrade again recreates both (idempotent round trip).
        await asyncio.to_thread(alembic_command.upgrade, cfg, "head")
        tables_after_up = await _inspect(engine, _table_names)
        assert "hired_agents" in tables_after_up
        seat_columns_after_up = await _inspect(engine, lambda conn: _column_names(conn, "agent_seats"))
        assert "model_family" in seat_columns_after_up
    finally:
        await engine.dispose()


async def test_hiring_chains_into_the_single_head() -> None:
    """Upgrading to head passes through 0043 and lands on the one head."""
    script = ScriptDirectory(str(_MIGRATIONS_DIR))
    heads = script.get_heads()
    assert len(heads) == 1
    assert _REVISION in {rev.revision for rev in script.walk_revisions(base=_PREVIOUS, head=heads[0])}
