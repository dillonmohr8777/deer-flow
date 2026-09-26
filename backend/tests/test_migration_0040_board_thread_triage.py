"""Migration round-trip tests for 0040_board_thread_triage."""

from __future__ import annotations

import asyncio

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.ext.asyncio import create_async_engine

from deerflow.persistence.bootstrap import _get_alembic_config

pytestmark = pytest.mark.asyncio


async def test_0040_adds_urgency_and_summary_columns(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    try:
        await asyncio.to_thread(command.upgrade, _get_alembic_config(engine), "0040_board_thread_triage")
        async with engine.connect() as conn:

            def _inspect(sync_conn):
                inspector = sa.inspect(sync_conn)
                cols = {c["name"]: c for c in inspector.get_columns("board_threads")}
                assert "urgency" in cols
                assert "summary" in cols
                assert cols["urgency"]["nullable"] is True
                assert cols["summary"]["nullable"] is True

            await conn.run_sync(_inspect)
    finally:
        await engine.dispose()


async def test_0040_downgrade_removes_columns(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    try:
        config = _get_alembic_config(engine)
        await asyncio.to_thread(command.upgrade, config, "0040_board_thread_triage")
        await asyncio.to_thread(command.downgrade, config, "0039_team_board_academy")
        async with engine.connect() as conn:

            def _inspect(sync_conn):
                inspector = sa.inspect(sync_conn)
                cols = {c["name"] for c in inspector.get_columns("board_threads")}
                assert "urgency" not in cols
                assert "summary" not in cols

            await conn.run_sync(_inspect)
    finally:
        await engine.dispose()


async def test_0040_is_the_single_head():
    from alembic.script import ScriptDirectory

    config = _get_alembic_config(create_async_engine("sqlite+aiosqlite:///:memory:"))
    heads = ScriptDirectory.from_config(config).get_heads()
    assert heads == ["0040_board_thread_triage"]
