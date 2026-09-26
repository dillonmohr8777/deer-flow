"""Migration round-trip tests for 0039_board_message_approval."""

from __future__ import annotations

import asyncio

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import create_async_engine

from deerflow.persistence.bootstrap import _MIGRATIONS_DIR, _get_alembic_config

pytestmark = pytest.mark.asyncio


async def test_0039_chains_into_the_single_head():
    """Guards against a repeat of the #38/#41 collision: two branches independently

    adding their own next revision after ``0038_board_threads`` (each PR here
    branches from ``lane/momo-week`` in isolation, so nothing merges this week --
    see the migration's docstring). Whichever PR's migration lands second must
    rename its file and re-chain ``down_revision`` onto the other's revision id,
    exactly like the ``0023``/``0025``/``0026`` precedents in this same
    directory; this test fails loudly the moment that hasn't happened yet.
    """
    script = ScriptDirectory(str(_MIGRATIONS_DIR))
    assert len(script.get_heads()) == 1


async def test_0039_adds_approved_at_column(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    try:
        await asyncio.to_thread(command.upgrade, _get_alembic_config(engine), "0039_board_message_approval")
        async with engine.connect() as conn:

            def _inspect(sync_conn):
                inspector = sa.inspect(sync_conn)
                message_cols = {c["name"] for c in inspector.get_columns("board_messages")}
                assert message_cols == {
                    "id",
                    "thread_id",
                    "author_kind",
                    "author_user_id",
                    "body",
                    "created_at",
                    "approved_at",
                }

            await conn.run_sync(_inspect)
    finally:
        await engine.dispose()


async def test_0039_downgrade_removes_column(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    try:
        config = _get_alembic_config(engine)
        await asyncio.to_thread(command.upgrade, config, "0039_board_message_approval")
        await asyncio.to_thread(command.downgrade, config, "0038_board_threads")
        async with engine.connect() as conn:

            def _inspect(sync_conn):
                inspector = sa.inspect(sync_conn)
                message_cols = {c["name"] for c in inspector.get_columns("board_messages")}
                assert "approved_at" not in message_cols

            await conn.run_sync(_inspect)
    finally:
        await engine.dispose()
