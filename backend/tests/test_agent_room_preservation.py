"""Private room persistence, real route admission, and retained tool handoffs."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from org_isolation_fixtures import ORG_S, STORAGE_S, USER_A, USER_B, USER_C, auth_headers, org_world  # noqa: F401

from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.deps import get_config
from app.gateway.routers import agent_room
from deerflow.config.app_config import AppConfig
from deerflow.persistence.agent_room import AgentRoomRepository
from deerflow.persistence.user.model import UserRow
from deerflow.tools.builtins.agent_room_tool import agent_room_post, agent_room_read
from deerflow.tools.tools import get_available_tools


async def _promote_and_authenticate(sf, monkeypatch):
    async with sf() as session, session.begin():
        await session.execute(sa.update(UserRow).where(UserRow.id.in_([USER_A, USER_C])).values(system_role="admin"))

    async def user_from_session(request):
        async with sf() as session:
            return await session.get(UserRow, request.cookies["access_token"])

    monkeypatch.setattr("app.gateway.deps.get_current_user_from_request", user_from_session)
    monkeypatch.setattr("app.gateway.routers.agent_room.get_current_user_from_request", user_from_session)


def _app(sf, *, enabled=True, repository=True):
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.state.agent_room_repo = AgentRoomRepository(sf) if repository else None
    app.dependency_overrides[get_config] = lambda: SimpleNamespace(private_workspace=SimpleNamespace(enabled=enabled))
    app.include_router(agent_room.router)
    return app


@pytest.mark.asyncio
async def test_real_admin_route_preserves_owner_isolation(org_world, monkeypatch):  # noqa: F811
    await _promote_and_authenticate(org_world, monkeypatch)
    app = _app(org_world)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        posted = await client.post(
            "/api/agent-room/messages",
            headers=auth_headers(USER_A, ORG_S),
            json={"body": "  Synthetic owner instruction  ", "author_kind": "agent", "user_id": USER_C},
        )
        assert posted.status_code == 201, posted.text
        assert (posted.json()["user_id"], posted.json()["author_kind"], posted.json()["body"]) == (USER_A, "owner", "Synthetic owner instruction")
        assert (await client.get("/api/agent-room/messages", headers=auth_headers(USER_C, ORG_S))).json()["messages"] == []
        mine = await client.get("/api/agent-room/messages", headers=auth_headers(USER_A, ORG_S))
        assert [m["id"] for m in mine.json()["messages"]] == [posted.json()["id"]]
        assert (await client.get("/api/agent-room/messages", headers=auth_headers(USER_B))).status_code == 404
        assert (await client.post("/api/agent-room/messages", headers=auth_headers(USER_B), json={"body": "denied"})).status_code == 404


@pytest.mark.asyncio
async def test_disabled_private_room_and_missing_persistence_fail_closed(org_world, monkeypatch):  # noqa: F811
    await _promote_and_authenticate(org_world, monkeypatch)
    for enabled, repository, expected in [(False, True, 404), (True, False, 503)]:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app(org_world, enabled=enabled, repository=repository)), base_url="http://test") as client:
            assert (await client.get("/api/agent-room/messages", headers=auth_headers(USER_A))).status_code == expected


@pytest.mark.asyncio
async def test_owner_message_validation_cannot_insert_blank_or_oversized_rows(org_world, monkeypatch):  # noqa: F811
    await _promote_and_authenticate(org_world, monkeypatch)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app(org_world)), base_url="http://test") as client:
        for text in ["   ", "x" * 4001]:
            assert (await client.post("/api/agent-room/messages", headers=auth_headers(USER_A), json={"body": text})).status_code == 422
        assert (await client.get("/api/agent-room/messages", headers=auth_headers(USER_A))).json()["messages"] == []


@pytest.mark.asyncio
async def test_real_room_tool_handoff_is_attributed_to_authenticated_actor(org_world, monkeypatch):  # noqa: F811
    await _promote_and_authenticate(org_world, monkeypatch)
    runtime = SimpleNamespace(context={"actor_user_id": USER_A, "user_id": STORAGE_S, "agent_id": "room-coordinator", "run_id": "synthetic-run"}, config={})
    result = await agent_room_post.coroutine(runtime=runtime, body="Synthetic handoff", message_type="handoff")
    assert "as Coordinator" in result
    history = json.loads(await agent_room_read.coroutine(runtime=runtime, limit=1))
    assert len(history) == 1
    row = history[0]
    assert (row["user_id"], row["author_kind"], row["agent_id"], row["run_id"], row["body"]) == (USER_A, "agent", "room-coordinator", "synthetic-run", "Synthetic handoff")
    assert await AgentRoomRepository(org_world).list_messages(user_id=USER_C) == []
    assert await AgentRoomRepository(org_world).list_messages(user_id=STORAGE_S) == []


@pytest.mark.asyncio
async def test_tool_refuses_nonadmin_disabled_and_missing_identity(org_world, monkeypatch):  # noqa: F811
    await _promote_and_authenticate(org_world, monkeypatch)
    denied = SimpleNamespace(context={"actor_user_id": USER_B}, config={})
    assert "owner only" in await agent_room_post.coroutine(runtime=denied, body="denied")
    async with org_world() as session, session.begin():
        await session.execute(sa.update(UserRow).where(UserRow.id == USER_A).values(disabled_at=datetime.now(UTC)))
    disabled = SimpleNamespace(context={"actor_user_id": USER_A}, config={})
    assert "owner only" in await agent_room_read.coroutine(runtime=disabled)
    assert "authenticated runtime" in await agent_room_post.coroutine(runtime=None, body="denied")
    assert await AgentRoomRepository(org_world).list_messages(user_id=USER_B) == []
    assert await AgentRoomRepository(org_world).list_messages(user_id=USER_A) == []


@pytest.mark.asyncio
async def test_tool_refuses_the_real_owner_on_a_channel_run(org_world, monkeypatch):  # noqa: F811
    """Defence in depth: a channel run must never reach the room, even for the owner.

    A channel run (GitHub webhook fan-out, a Telegram bot, etc.) resolves the
    runtime actor to the channel's bound owner regardless of which external
    person actually triggered it, so an outside commenter or a non-owner chat
    member looks identical to ``USER_A`` here. The lead-agent factory already
    withholds these tools from channel runs; this is the in-tool mirror for
    any future code path (custom factories, tests) that re-attaches them
    directly without going through the factory.
    """
    await _promote_and_authenticate(org_world, monkeypatch)
    for channel_name in ("github", "telegram"):
        runtime = SimpleNamespace(context={"actor_user_id": USER_A, "channel_name": channel_name}, config={})
        read_result = await agent_room_read.coroutine(runtime=runtime)
        post_result = await agent_room_post.coroutine(runtime=runtime, body="hijacked")
        assert channel_name in read_result, channel_name
        assert channel_name in post_result, channel_name
    assert await AgentRoomRepository(org_world).list_messages(user_id=USER_A) == []


@pytest.mark.asyncio
async def test_invalid_owner_resolution_pair_cannot_reach_storage(monkeypatch):
    async def missing_owner(_runtime):
        return None, None

    monkeypatch.setattr("deerflow.tools.builtins.agent_room_tool._owner_repository", missing_owner)
    runtime = SimpleNamespace(context={"actor_user_id": USER_A}, config={})
    assert "authenticated owner" in await agent_room_read.coroutine(runtime=runtime)
    assert "authenticated owner" in await agent_room_post.coroutine(runtime=runtime, body="denied")


@pytest.mark.parametrize("enabled", [False, True])
def test_room_tool_visibility_retains_private_workspace_switch(enabled):
    config = AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}, "private_workspace": {"enabled": enabled}})
    names = {t.name for t in get_available_tools(app_config=config, include_mcp=False, groups=[])}
    assert ("agent_room_read" in names) is enabled
    assert ("agent_room_post" in names) is enabled
