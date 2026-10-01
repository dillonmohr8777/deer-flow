"""Upgrade both shipped migration histories without rewriting their stamps."""

from __future__ import annotations

import asyncio

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import create_async_engine

from deerflow.persistence.bootstrap import _get_alembic_config, bootstrap_schema

ROOM = "0040_agent_room_messages"
LANE = "0046_organization_entitlements"
MERGE = "0047_merge_agent_room_exec"
PREVIOUS = "0039_team_board_academy"
# The single head as of queue item e14's ceo_desk_digests migration. Chains
# straight after MERGE, so MERGE's own parent-edge assertions below stay
# valid; only "what's the current head" moves when a new migration lands.
HEAD = "0048_ceo_desk_digests"


def test_merge_preserves_both_published_parent_edges():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    script = ScriptDirectory.from_config(_get_alembic_config(engine))
    assert script.get_heads() == [HEAD]
    assert script.get_revision(ROOM).down_revision == PREVIOUS
    assert script.get_revision("0040_agent_seats").down_revision == PREVIOUS
    assert set(script.get_revision(MERGE).down_revision) == {ROOM, LANE}


@pytest.mark.asyncio
@pytest.mark.parametrize("origin", [PREVIOUS, ROOM, LANE])
async def test_existing_history_upgrades_and_preserves_owner_rows(tmp_path, origin):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'upgrade.db'}")
    cfg = _get_alembic_config(engine)
    try:
        await asyncio.to_thread(command.upgrade, cfg, origin)
        async with engine.begin() as conn:
            await conn.execute(
                sa.text("INSERT INTO users (id, email, password_hash, system_role, created_at, needs_setup, token_version) VALUES (:id, :email, :hash, 'admin', :created, 0, 17)"),
                {"id": "retained-owner", "email": "owner@example.invalid", "hash": "synthetic-retained-hash", "created": "2026-09-29 16:00:00"},
            )
            if origin == ROOM:
                await conn.execute(
                    sa.text(
                        "INSERT INTO agent_room_messages (id, user_id, author_kind, agent_id, agent_role, message_type, body, run_id, created_at) "
                        "VALUES ('retained-room-row', 'retained-owner', 'agent', 'room-coordinator', 'Coordinator', 'handoff', "
                        "'Synthetic handoff must survive', 'retained-run', :created)"
                    ),
                    {"created": "2026-09-29 16:01:00"},
                )
            user_before = (await conn.execute(sa.text("SELECT * FROM users WHERE id='retained-owner'"))).mappings().one()
            room_before = (await conn.execute(sa.text("SELECT * FROM agent_room_messages"))).mappings().all() if origin == ROOM else []

        # Exercise the actual application bootstrap, not a stamp shortcut.
        await bootstrap_schema(engine, backend="sqlite")
        async with engine.connect() as conn:
            assert (await conn.execute(sa.text("SELECT version_num FROM alembic_version"))).scalar_one() == HEAD
            assert (await conn.execute(sa.text("SELECT * FROM users WHERE id='retained-owner'"))).mappings().one() == user_before
            assert (await conn.execute(sa.text("SELECT * FROM agent_room_messages"))).mappings().all() == room_before
            tables = await conn.run_sync(lambda sync: set(sa.inspect(sync).get_table_names()))
            assert {"agent_room_messages", "agent_seats", "hired_agents", "organization_entitlements"} <= tables

        await bootstrap_schema(engine, backend="sqlite")
        async with engine.connect() as conn:
            assert (await conn.execute(sa.text("SELECT count(*) FROM users WHERE id='retained-owner'"))).scalar_one() == 1
            assert (await conn.execute(sa.text("SELECT count(*) FROM agent_room_messages"))).scalar_one() == len(room_before)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_empty_bootstrap_has_room_and_executive_schema(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'empty.db'}")
    try:
        await bootstrap_schema(engine, backend="sqlite")
        async with engine.connect() as conn:
            assert (await conn.execute(sa.text("SELECT version_num FROM alembic_version"))).scalar_one() == HEAD
            tables = await conn.run_sync(lambda sync: set(sa.inspect(sync).get_table_names()))
            assert {"agent_room_messages", "agent_seats", "hired_agents", "organization_entitlements"} <= tables
    finally:
        await engine.dispose()
