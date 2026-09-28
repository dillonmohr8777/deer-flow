"""Migration round-trip tests for 0040_organization_entitlements."""

from __future__ import annotations

import asyncio

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.ext.asyncio import create_async_engine

from deerflow.persistence.bootstrap import _get_alembic_config

pytestmark = pytest.mark.asyncio


async def test_0040_creates_organization_entitlements(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    try:
        await asyncio.to_thread(command.upgrade, _get_alembic_config(engine), "0040_organization_entitlements")
        async with engine.connect() as conn:

            def _inspect(sync_conn):
                inspector = sa.inspect(sync_conn)
                assert inspector.has_table("organization_entitlements")
                cols = {c["name"] for c in inspector.get_columns("organization_entitlements")}
                assert cols == {
                    "organization_id",
                    "key",
                    "limit_value",
                    "source",
                    "status",
                    "created_at",
                    "updated_at",
                }
                indexes = {i["name"] for i in inspector.get_indexes("organization_entitlements")}
                assert "ix_organization_entitlements_organization_id" in indexes
                pk = inspector.get_pk_constraint("organization_entitlements")
                assert pk["constrained_columns"] == ["organization_id", "key"]

            await conn.run_sync(_inspect)
    finally:
        await engine.dispose()


async def test_0040_downgrade_drops_organization_entitlements(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    try:
        cfg = _get_alembic_config(engine)
        await asyncio.to_thread(command.upgrade, cfg, "0040_organization_entitlements")
        await asyncio.to_thread(command.downgrade, cfg, "0039_team_board_academy")
        async with engine.connect() as conn:

            def _inspect(sync_conn):
                inspector = sa.inspect(sync_conn)
                assert not inspector.has_table("organization_entitlements")

            await conn.run_sync(_inspect)
    finally:
        await engine.dispose()


async def test_0040_chains_into_the_single_head(tmp_path):
    """Guard against a second migration also chaining off 0039 (see f29/f20)."""
    from alembic.script import ScriptDirectory

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    try:
        cfg = _get_alembic_config(engine)
        script = ScriptDirectory.from_config(cfg)
        heads = script.get_heads()
        assert len(heads) == 1, f"expected a single alembic head, found {heads}"
    finally:
        await engine.dispose()
