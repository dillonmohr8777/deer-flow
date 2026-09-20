"""Migration coverage for verified private-organization backfill."""

from __future__ import annotations

import asyncio
import sqlite3

import pytest
from alembic import command

import deerflow.persistence.models  # noqa: F401 -- registers ORM models
from deerflow.persistence.agents.model import AgentRow
from deerflow.persistence.bootstrap import _get_alembic_config
from deerflow.persistence.engine import close_engine, get_engine, get_session_factory, init_engine
from deerflow.persistence.organizations.identity import private_organization_id
from deerflow.persistence.run.model import RunRow
from deerflow.persistence.thread_meta.model import ThreadMetaRow
from deerflow.persistence.user.model import UserRow

REVISION = "0027_organization_backfill"
PREVIOUS = "0026_organization_foundation"


@pytest.mark.asyncio
async def test_0027_backfills_only_verified_private_ownership_and_reverses(tmp_path):
    db_path = tmp_path / "organization-backfill.db"
    await init_engine("sqlite", url=f"sqlite+aiosqlite:///{db_path.as_posix()}", sqlite_dir=str(tmp_path))
    try:
        engine = get_engine()
        assert engine is not None
        cfg = _get_alembic_config(engine)
        await asyncio.to_thread(command.downgrade, cfg, PREVIOUS)
        user_id = "2f1a0a64-0d14-4d27-b4b2-f824d510be78"
        session_factory = get_session_factory()
        async with session_factory() as session:
            session.add(UserRow(id=user_id, email="owner@example.com", system_role="user", needs_setup=False, token_version=0))
            session.add(AgentRow(id="agent", user_id=user_id, name="agent", config={}, soul=""))
            session.add(ThreadMetaRow(thread_id="thread", user_id=user_id, status="idle", metadata_json={}))
            session.add(RunRow(run_id="run", thread_id="thread", user_id=user_id, status="pending", metadata_json={}, kwargs_json={}))
            session.add(ThreadMetaRow(thread_id="orphan", user_id="missing-user", status="idle", metadata_json={}))
            await session.commit()

        await asyncio.to_thread(command.upgrade, cfg, REVISION)
        organization_id = private_organization_id(user_id)
        with sqlite3.connect(db_path) as raw:
            assert raw.execute("SELECT organization_id FROM agents WHERE id = 'agent'").fetchone() == (organization_id,)
            assert raw.execute("SELECT organization_id FROM threads_meta WHERE thread_id = 'thread'").fetchone() == (organization_id,)
            assert raw.execute("SELECT organization_id FROM runs WHERE run_id = 'run'").fetchone() == (organization_id,)
            assert raw.execute("SELECT organization_id FROM threads_meta WHERE thread_id = 'orphan'").fetchone() == (None,)
            assert raw.execute("SELECT role, status FROM organization_members WHERE organization_id = ? AND user_id = ?", (organization_id, user_id)).fetchone() == ("owner", "active")

        await asyncio.to_thread(command.downgrade, cfg, PREVIOUS)
        with sqlite3.connect(db_path) as raw:
            assert raw.execute("SELECT organization_id FROM agents WHERE id = 'agent'").fetchone() == (None,)
            assert raw.execute("SELECT 1 FROM organizations WHERE id = ?", (organization_id,)).fetchone() is None
    finally:
        await close_engine()
