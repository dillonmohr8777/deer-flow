"""Migration round-trip tests for 0034_clients."""

from __future__ import annotations

import asyncio

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.ext.asyncio import create_async_engine

from deerflow.persistence.bootstrap import _get_alembic_config
from deerflow.persistence.migrations import _helpers  # noqa: F401  (ensures helpers importable)

pytestmark = pytest.mark.asyncio


async def test_0034_creates_clients_and_assignments_and_project_column(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    try:
        await asyncio.to_thread(command.upgrade, _get_alembic_config(engine), "0034_clients")
        async with engine.connect() as conn:

            def _inspect(sync_conn):
                inspector = sa.inspect(sync_conn)
                assert inspector.has_table("clients")
                client_cols = {c["name"] for c in inspector.get_columns("clients")}
                assert client_cols == {
                    "id",
                    "organization_id",
                    "display_name",
                    "aliases",
                    "status",
                    "email_domains",
                    "slack_channel_ids",
                    "registry_id",
                    "notes",
                    "created_at",
                    "updated_at",
                }
                client_indexes = {i["name"] for i in inspector.get_indexes("clients")}
                assert "ix_clients_organization_id" in client_indexes
                assert "ix_clients_status" in client_indexes
                assert "ix_clients_registry_id" in client_indexes
                unique_constraints = {u["name"] for u in inspector.get_unique_constraints("clients")}
                assert "uq_clients_org_registry_id" in unique_constraints

                assert inspector.has_table("client_assignments")
                assignment_cols = {c["name"] for c in inspector.get_columns("client_assignments")}
                assert assignment_cols == {"client_id", "user_id", "organization_id", "role", "created_at", "updated_at"}
                pk = inspector.get_pk_constraint("client_assignments")
                assert set(pk["constrained_columns"]) == {"client_id", "user_id"}

                project_cols = {c["name"] for c in inspector.get_columns("projects")}
                assert "client_id" in project_cols
                project_indexes = {i["name"] for i in inspector.get_indexes("projects")}
                assert "ix_projects_client_id" in project_indexes

            await conn.run_sync(_inspect)
    finally:
        await engine.dispose()


async def test_0034_downgrade_removes_tables_and_column(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    try:
        config = _get_alembic_config(engine)
        await asyncio.to_thread(command.upgrade, config, "0034_clients")
        await asyncio.to_thread(command.downgrade, config, "0033_audit_events")
        async with engine.connect() as conn:

            def _inspect(sync_conn):
                inspector = sa.inspect(sync_conn)
                assert not inspector.has_table("clients")
                assert not inspector.has_table("client_assignments")
                assert "client_id" not in {c["name"] for c in inspector.get_columns("projects")}

            await conn.run_sync(_inspect)
    finally:
        await engine.dispose()
