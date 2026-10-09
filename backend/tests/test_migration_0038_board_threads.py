"""Migration round-trip tests for 0038_board_threads."""

from __future__ import annotations

import asyncio

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.ext.asyncio import create_async_engine

from deerflow.persistence.bootstrap import _get_alembic_config

pytestmark = pytest.mark.asyncio


async def test_0038_creates_board_threads_and_messages(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    try:
        await asyncio.to_thread(command.upgrade, _get_alembic_config(engine), "0038_board_threads")
        async with engine.connect() as conn:

            def _inspect(sync_conn):
                inspector = sa.inspect(sync_conn)
                assert inspector.has_table("board_threads")
                thread_cols = {c["name"] for c in inspector.get_columns("board_threads")}
                assert thread_cols == {
                    "id",
                    "organization_id",
                    "client_id",
                    "kind",
                    "status",
                    "subject",
                    "created_by_user_id",
                    "created_at",
                    "updated_at",
                }
                thread_indexes = {i["name"] for i in inspector.get_indexes("board_threads")}
                assert "ix_board_threads_organization_id" in thread_indexes
                assert "ix_board_threads_client_id" in thread_indexes
                assert "ix_board_threads_status" in thread_indexes
                assert "ix_board_threads_created_by_user_id" in thread_indexes
                thread_pk = inspector.get_pk_constraint("board_threads")
                assert thread_pk["constrained_columns"] == ["id"]

                assert inspector.has_table("board_messages")
                message_cols = {c["name"] for c in inspector.get_columns("board_messages")}
                assert message_cols == {
                    "id",
                    "thread_id",
                    "author_kind",
                    "author_user_id",
                    "body",
                    "created_at",
                }
                message_indexes = {i["name"] for i in inspector.get_indexes("board_messages")}
                assert "ix_board_messages_thread_id" in message_indexes
                assert "ix_board_messages_author_user_id" in message_indexes
                message_pk = inspector.get_pk_constraint("board_messages")
                assert message_pk["constrained_columns"] == ["id"]

            await conn.run_sync(_inspect)
    finally:
        await engine.dispose()


async def test_0038_downgrade_removes_tables(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    try:
        config = _get_alembic_config(engine)
        await asyncio.to_thread(command.upgrade, config, "0038_board_threads")
        await asyncio.to_thread(command.downgrade, config, "0037_pat_organization")
        async with engine.connect() as conn:

            def _inspect(sync_conn):
                inspector = sa.inspect(sync_conn)
                assert not inspector.has_table("board_threads")
                assert not inspector.has_table("board_messages")

            await conn.run_sync(_inspect)
    finally:
        await engine.dispose()
