"""Migration tests for the additive organization foundation."""

from __future__ import annotations

import asyncio
import sqlite3

import pytest
from alembic import command

import deerflow.persistence.models  # noqa: F401 -- registers ORM models
from deerflow.persistence.bootstrap import _get_alembic_config
from deerflow.persistence.engine import close_engine, get_engine, init_engine

pytestmark = pytest.mark.asyncio

REVISION = "0026_organization_foundation"
PREVIOUS = "0025_repair_run_change_seq"
RESOURCE_TABLES = {
    "agents",
    "projects",
    "project_documents",
    "threads_meta",
    "runs",
    "scheduled_tasks",
    "scheduled_task_runs",
    "subagent_batches",
    "channel_connections",
    "channel_oauth_states",
    "channel_conversations",
    "mcp_tasks",
    "feedback",
}
ORGANIZATION_TABLES = {"organizations", "organization_members", "organization_delegations"}


def _schema_state(
    db_path,
) -> tuple[set[str], dict[str, dict[str, bool]], dict[str, set[str]], str | None]:
    with sqlite3.connect(db_path) as raw:
        tables = {row[0] for row in raw.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        columns = {table: {row[1]: not bool(row[3]) for row in raw.execute(f"PRAGMA table_info({table})")} for table in RESOURCE_TABLES if table in tables}
        indexes = {table: {row[1] for row in raw.execute(f"PRAGMA index_list({table})")} for table in RESOURCE_TABLES | ORGANIZATION_TABLES if table in tables}
        version = raw.execute("SELECT version_num FROM alembic_version").fetchone()
    return tables, columns, indexes, version[0] if version else None


async def test_0026_adds_and_removes_only_organization_foundation_schema(tmp_path):
    db_path = tmp_path / "organization-foundation.db"
    await init_engine("sqlite", url=f"sqlite+aiosqlite:///{db_path.as_posix()}", sqlite_dir=str(tmp_path))
    try:
        engine = get_engine()
        assert engine is not None
        cfg = _get_alembic_config(engine)

        await asyncio.to_thread(command.downgrade, cfg, PREVIOUS)
        tables, columns, indexes, version = _schema_state(db_path)
        assert RESOURCE_TABLES <= tables
        assert "run_change_clock" in tables
        assert not (ORGANIZATION_TABLES & tables)
        assert all("organization_id" not in table_columns for table_columns in columns.values())
        assert version == PREVIOUS

        await asyncio.to_thread(command.upgrade, cfg, REVISION)
        tables, columns, indexes, version = _schema_state(db_path)
        assert ORGANIZATION_TABLES <= tables
        assert all(columns[table].get("organization_id") is True for table in RESOURCE_TABLES)
        assert all(f"ix_{table}_organization_id" in indexes[table] for table in RESOURCE_TABLES)
        assert {"ix_organizations_slug"} <= indexes["organizations"]
        assert {"ix_organization_members_user_id", "ix_organization_members_status"} <= indexes["organization_members"]
        assert "ix_organization_delegations_subject" in indexes["organization_delegations"]
        with sqlite3.connect(db_path) as raw:
            organization_columns = {row[1] for row in raw.execute("PRAGMA table_info(organizations)")}
            membership_columns = {row[1] for row in raw.execute("PRAGMA table_info(organization_members)")}
            delegation_columns = {row[1] for row in raw.execute("PRAGMA table_info(organization_delegations)")}
        assert organization_columns == {"id", "slug", "name", "status", "created_at", "updated_at"}
        assert membership_columns == {"organization_id", "user_id", "role", "status", "created_at", "updated_at"}
        assert delegation_columns == {
            "id",
            "organization_id",
            "subject_type",
            "subject_id",
            "owner_user_id",
            "scopes",
            "status",
            "expires_at",
            "created_at",
            "updated_at",
        }
        assert version == REVISION

        await asyncio.to_thread(command.downgrade, cfg, PREVIOUS)
        tables, columns, _, version = _schema_state(db_path)
        assert RESOURCE_TABLES <= tables
        assert "run_change_clock" in tables
        assert not (ORGANIZATION_TABLES & tables)
        assert all("organization_id" not in table_columns for table_columns in columns.values())
        assert version == PREVIOUS

        await asyncio.to_thread(command.upgrade, cfg, REVISION)
        tables, columns, _, version = _schema_state(db_path)
        assert ORGANIZATION_TABLES <= tables
        assert all(columns[table].get("organization_id") is True for table in RESOURCE_TABLES)
        assert version == REVISION
    finally:
        await close_engine()
