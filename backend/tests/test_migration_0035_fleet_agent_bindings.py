"""Migration round-trip tests for 0035_fleet_agent_bindings."""

from __future__ import annotations

import asyncio

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.ext.asyncio import create_async_engine

from deerflow.persistence.bootstrap import _get_alembic_config
from deerflow.persistence.migrations import _helpers  # noqa: F401  (ensures helpers importable)

pytestmark = pytest.mark.asyncio


async def test_0035_creates_fleet_agent_bindings(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    try:
        await asyncio.to_thread(command.upgrade, _get_alembic_config(engine), "0035_fleet_agent_bindings")
        async with engine.connect() as conn:

            def _inspect(sync_conn):
                inspector = sa.inspect(sync_conn)
                assert inspector.has_table("fleet_agent_bindings")
                cols = {c["name"] for c in inspector.get_columns("fleet_agent_bindings")}
                assert cols == {
                    "id",
                    "organization_id",
                    "client_id",
                    "template_id",
                    "template_version",
                    "agent_name",
                    "agent_owner_user_id",
                    "scheduled_task_id",
                    "created_at",
                    "updated_at",
                }
                indexes = {i["name"] for i in inspector.get_indexes("fleet_agent_bindings")}
                assert "ix_fleet_agent_bindings_organization_id" in indexes
                assert "ix_fleet_agent_bindings_client_id" in indexes
                unique_constraints = {u["name"] for u in inspector.get_unique_constraints("fleet_agent_bindings")}
                assert "uq_fleet_agent_bindings_client_template" in unique_constraints
                pk = inspector.get_pk_constraint("fleet_agent_bindings")
                assert set(pk["constrained_columns"]) == {"id"}

            await conn.run_sync(_inspect)
    finally:
        await engine.dispose()


async def test_0035_downgrade_removes_table(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    try:
        config = _get_alembic_config(engine)
        await asyncio.to_thread(command.upgrade, config, "0035_fleet_agent_bindings")
        await asyncio.to_thread(command.downgrade, config, "0034_clients")
        async with engine.connect() as conn:

            def _inspect(sync_conn):
                inspector = sa.inspect(sync_conn)
                assert not inspector.has_table("fleet_agent_bindings")

            await conn.run_sync(_inspect)
    finally:
        await engine.dispose()
