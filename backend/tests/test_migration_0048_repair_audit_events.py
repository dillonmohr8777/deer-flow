"""Forward-only audit repair; fixtures are synthetic and local."""

from __future__ import annotations

import asyncio
import json
import sqlite3

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deerflow.persistence.audit_events import AuditEventRepository
from deerflow.persistence.bootstrap import _get_alembic_config, bootstrap_schema

PREVIOUS = "0047_merge_agent_room_exec"
REPAIR = "0048_repair_audit_events"
INDEXES = {"ix_audit_events_occurred_at", "ix_audit_events_action", "ix_audit_events_organization_id", "ix_audit_events_actor_user_id"}


def preserved_snapshot(db):
    with sqlite3.connect(db) as conn:
        schema = conn.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE tbl_name NOT IN ('audit_events','alembic_version') ORDER BY type,name,tbl_name").fetchall()
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT IN ('audit_events','alembic_version') ORDER BY name")]
        rows = {table: conn.execute('SELECT * FROM "' + table + '"').fetchall() for table in tables}
        return schema, rows


def assert_audit_shape(db):
    with sqlite3.connect(db) as conn:
        assert {r[1] for r in conn.execute("PRAGMA table_info(audit_events)")} == {"id", "occurred_at", "actor_user_id", "organization_id", "action", "target_type", "target_id", "outcome", "ip", "user_agent", "details"}
        assert {r[1] for r in conn.execute("PRAGMA index_list(audit_events)") if not r[1].startswith("sqlite_autoindex_")} == INDEXES
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone() == (REPAIR,)


@pytest.mark.asyncio
async def test_repair_is_a_single_forward_successor():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        script = ScriptDirectory.from_config(_get_alembic_config(engine))
        assert script.get_heads() == [REPAIR]
        assert script.get_revision(REPAIR).down_revision == PREVIOUS
        parents = script.get_revision(PREVIOUS).down_revision
        assert isinstance(parents, tuple)
        assert set(parents) == {"0040_agent_room_messages", "0046_organization_entitlements"}
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("origin", ["missing_table", "healthy", "missing_index"])
async def test_managed_0047_repair_preserves_existing_schema_rows_and_audit_history(tmp_path, origin):
    db = tmp_path / "managed.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db}")
    cfg = _get_alembic_config(engine)
    try:
        await asyncio.to_thread(command.upgrade, cfg, PREVIOUS)
        with sqlite3.connect(db) as conn:
            conn.executescript(
                "INSERT INTO users(id,email,password_hash,system_role,created_at,needs_setup,token_version) "
                "VALUES('retained-owner','owner@example.invalid','synthetic-hash','admin','2026-09-29 16:00:00',0,17);"
                "INSERT INTO agent_room_messages(id,user_id,author_kind,agent_role,message_type,body,created_at) "
                "VALUES('retained-room','retained-owner','agent','Coordinator','handoff','Synthetic retained handoff','2026-09-29 16:01:00');"
                "CREATE TABLE checkpoints(thread_id TEXT PRIMARY KEY,payload BLOB);"
                "INSERT INTO checkpoints VALUES('retained-thread',X'1234');"
            )
            if origin == "missing_table":
                conn.execute("DROP TABLE audit_events")
            else:
                conn.execute("INSERT INTO audit_events(id,occurred_at,action,outcome,details) VALUES('retained-audit','2026-09-29 16:00:00','synthetic.before','success','{\"retained\":true}')")
                if origin == "missing_index":
                    conn.execute("DROP INDEX ix_audit_events_action")
        before = preserved_snapshot(db)
        await bootstrap_schema(engine, backend="sqlite")
        assert_audit_shape(db)
        assert preserved_snapshot(db) == before
        repo = AuditEventRepository(async_sessionmaker(engine, expire_on_commit=False))
        await repo.record(action="synthetic.after", outcome="denied", details={"api_key": "synthetic-secret", "reason": "offline_fixture"})
        result = await repo.list(organization_id=None, action_prefix="synthetic.")
        assert len(result[0]) == (1 if origin == "missing_table" else 2)
        with sqlite3.connect(db) as conn:
            details = json.loads(conn.execute("SELECT details FROM audit_events WHERE action='synthetic.after'").fetchone()[0])
            assert details["api_key"] != "synthetic-secret" and details["reason"] == "offline_fixture"
            audit_rows = conn.execute("SELECT * FROM audit_events ORDER BY id").fetchall()
        await bootstrap_schema(engine, backend="sqlite")
        await asyncio.to_thread(command.downgrade, cfg, PREVIOUS)
        with sqlite3.connect(db) as conn:
            assert conn.execute("SELECT * FROM audit_events ORDER BY id").fetchall() == audit_rows
        await bootstrap_schema(engine, backend="sqlite")
        assert_audit_shape(db)
        assert preserved_snapshot(db) == before
        with sqlite3.connect(db) as conn:
            assert conn.execute("SELECT * FROM audit_events ORDER BY id").fetchall() == audit_rows
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("drift", ["missing_column", "wrong_index", "wrong_nullability", "extra_unique_index"])
async def test_incompatible_partial_audit_schema_refuses_upgrade_without_restamp(tmp_path, drift):
    db = tmp_path / "drift.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db}")
    cfg = _get_alembic_config(engine)
    try:
        await asyncio.to_thread(command.upgrade, cfg, PREVIOUS)
        with sqlite3.connect(db) as conn:
            if drift == "extra_unique_index":
                conn.execute("CREATE UNIQUE INDEX unexpected_audit_outcome ON audit_events(outcome)")
            elif drift == "wrong_index":
                conn.execute("DROP INDEX ix_audit_events_action")
                conn.execute("CREATE INDEX ix_audit_events_action ON audit_events(outcome)")
            elif drift == "missing_column":
                conn.execute("ALTER TABLE audit_events DROP COLUMN details")
            else:
                original_sql = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='audit_events'").fetchone()[0]
                assert "occurred_at DATETIME NOT NULL" in original_sql
                conn.execute("DROP TABLE audit_events")
                conn.execute(original_sql.replace("occurred_at DATETIME NOT NULL", "occurred_at DATETIME"))
        before = preserved_snapshot(db)
        with sqlite3.connect(db) as conn:
            complete_schema_before = conn.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name,tbl_name").fetchall()
        with pytest.raises(RuntimeError, match="audit_events.*incompatible"):
            await bootstrap_schema(engine, backend="sqlite")
        with sqlite3.connect(db) as conn:
            assert conn.execute("SELECT version_num FROM alembic_version").fetchone() == (PREVIOUS,)
            assert conn.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name,tbl_name").fetchall() == complete_schema_before
        assert preserved_snapshot(db) == before
    finally:
        await engine.dispose()
