"""Migration round-trip tests for 0048_board_message_delivered_at (f174: the
first cut of this migration chained onto this branch's own then-current head
(0046_organization_entitlements) rather than the lane's, producing two
alembic heads once merged -- see test_0040_chains_into_the_single_head."""

from __future__ import annotations

import asyncio

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.ext.asyncio import create_async_engine

from deerflow.persistence.bootstrap import _get_alembic_config

pytestmark = pytest.mark.asyncio


async def test_0048_adds_board_messages_delivered_at(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    try:
        await asyncio.to_thread(command.upgrade, _get_alembic_config(engine), "0048_board_message_delivered_at")
        async with engine.connect() as conn:

            def _inspect(sync_conn):
                inspector = sa.inspect(sync_conn)
                assert inspector.has_table("board_messages")
                cols = {c["name"]: c for c in inspector.get_columns("board_messages")}
                assert "delivered_at" in cols
                assert cols["delivered_at"]["nullable"] is True

            await conn.run_sync(_inspect)
    finally:
        await engine.dispose()


async def test_0048_downgrade_drops_delivered_at(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    try:
        cfg = _get_alembic_config(engine)
        await asyncio.to_thread(command.upgrade, cfg, "0048_board_message_delivered_at")
        await asyncio.to_thread(command.downgrade, cfg, "0047_merge_agent_room_exec")
        async with engine.connect() as conn:

            def _inspect(sync_conn):
                inspector = sa.inspect(sync_conn)
                cols = {c["name"] for c in inspector.get_columns("board_messages")}
                assert "delivered_at" not in cols

            await conn.run_sync(_inspect)
    finally:
        await engine.dispose()


async def test_0048_chains_into_the_single_head(tmp_path):
    """Guard against a second migration also chaining off 0047 (see f174)."""
    from alembic.script import ScriptDirectory

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    try:
        cfg = _get_alembic_config(engine)
        script = ScriptDirectory.from_config(cfg)
        heads = script.get_heads()
        assert len(heads) == 1, f"expected a single alembic head, found {heads}"
    finally:
        await engine.dispose()
