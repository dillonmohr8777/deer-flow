"""Migration round-trip tests for 0039_board_message_approval."""

from __future__ import annotations

import asyncio

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.ext.asyncio import create_async_engine

from deerflow.persistence.bootstrap import _get_alembic_config

pytestmark = pytest.mark.asyncio


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
