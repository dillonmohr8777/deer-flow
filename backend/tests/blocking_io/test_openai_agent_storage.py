"""The hosted-agent admission, schema migration and leases stay off-loop."""

import asyncio
import sqlite3

import pytest

from app.gateway.openai_agent_service import OpenAIAgentService


@pytest.mark.asyncio
async def test_agent_admission_and_watchdog_storage_do_not_block_event_loop(tmp_path):
    service = OpenAIAgentService(tmp_path / "agents.sqlite")
    row, admitted = await service._storage("create", "alice-org", "Task", "hashed-key", "hashed-input")
    assert admitted
    await service._storage("bind", row["id"], "alice-org", "provider-session", "in_progress")
    assert len(await service.list_sessions("alice-org")) == 1
    assert await service.list_sessions("bob-org") == []

    def expire():
        with sqlite3.connect(service.path) as db:
            db.execute("UPDATE deadlines SET expires_at=0")

    await asyncio.to_thread(expire)
    claim = (await service._storage("due"))[0]
    await service._storage("deadline_sent", row["id"], "alice-org", claim["expires_at"], claim["lease_expires_at"])
    observed = await service._storage("snapshot", row["id"], "alice-org", "idle", {"id": "root", "status": "cancelled"})
    assert not observed["deadline_pending"]
    assert await service._storage("due") == []
