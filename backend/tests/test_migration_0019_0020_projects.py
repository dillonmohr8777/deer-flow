"""Migration tests for 0019_projects and 0020_threads_meta_project_id."""

from __future__ import annotations

import asyncio

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.ext.asyncio import create_async_engine

from deerflow.persistence.bootstrap import _get_alembic_config
from deerflow.persistence.engine import close_engine, init_engine
from deerflow.persistence.migrations import _helpers  # noqa: F401  (ensures helpers importable)

pytestmark = pytest.mark.asyncio


async def _fresh_db(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
    return url


async def test_0019_creates_projects_table(tmp_path):
    # Pin the schema to this revision: later migrations (0026 organization
    # foundation) add columns to ``projects`` that 0019 does not own.
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    try:
        await asyncio.to_thread(command.upgrade, _get_alembic_config(engine), "0019_projects")
        async with engine.connect() as conn:

            def _inspect(sync_conn):
                inspector = sa.inspect(sync_conn)
                assert inspector.has_table("projects")
                cols = {c["name"]: c for c in inspector.get_columns("projects")}
                assert set(cols) == {
                    "id",
                    "user_id",
                    "name",
                    "instructions",
                    "presentation",
                    "status",
                    "created_at",
                    "updated_at",
                }
                index_names = {i["name"] for i in inspector.get_indexes("projects")}
                assert "ix_projects_user_id" in index_names
                assert "ix_projects_status" in index_names

            await conn.run_sync(_inspect)
    finally:
        await engine.dispose()


async def test_0020_adds_project_id_column(tmp_path):
    await _fresh_db(tmp_path)
    try:
        from deerflow.persistence.engine import get_engine

        engine = get_engine()
        async with engine.connect() as conn:

            def _inspect(sync_conn):
                inspector = sa.inspect(sync_conn)
                cols = {c["name"] for c in inspector.get_columns("threads_meta")}
                assert "project_id" in cols
                index_names = {i["name"] for i in inspector.get_indexes("threads_meta")}
                assert "ix_threads_meta_project_id" in index_names

            await conn.run_sync(_inspect)
    finally:
        await close_engine()
