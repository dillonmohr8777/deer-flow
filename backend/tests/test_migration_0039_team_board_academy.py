"""Migration round-trip tests for 0039_team_board_academy."""

from __future__ import annotations

import asyncio

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.ext.asyncio import create_async_engine

from deerflow.persistence.bootstrap import _get_alembic_config

pytestmark = pytest.mark.asyncio

_TABLES = ("team_channels", "team_messages", "academy_progress")


async def test_0039_creates_and_drops_team_and_academy_tables(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    try:
        config = _get_alembic_config(engine)
        await asyncio.to_thread(command.upgrade, config, "0039_team_board_academy")
        async with engine.connect() as conn:

            def _inspect(sync_conn):
                inspector = sa.inspect(sync_conn)
                for table in _TABLES:
                    assert inspector.has_table(table), table
                assert {c["name"] for c in inspector.get_columns("team_channels")} == {
                    "id",
                    "organization_id",
                    "slug",
                    "name",
                    "topic",
                    "created_by_user_id",
                    "created_at",
                    "updated_at",
                }
                assert {c["name"] for c in inspector.get_columns("team_messages")} == {"id", "channel_id", "author_user_id", "body", "created_at"}
                assert inspector.get_pk_constraint("academy_progress")["constrained_columns"] == ["organization_id", "user_id", "lesson_id"]
                uniques = {u["name"] for u in inspector.get_unique_constraints("team_channels")}
                assert "uq_team_channels_org_slug" in uniques

            await conn.run_sync(_inspect)

        await asyncio.to_thread(command.downgrade, config, "0038_board_threads")
        async with engine.connect() as conn:

            def _gone(sync_conn):
                inspector = sa.inspect(sync_conn)
                for table in _TABLES:
                    assert not inspector.has_table(table), table
                assert inspector.has_table("board_threads")

            await conn.run_sync(_gone)
    finally:
        await engine.dispose()
