"""Regression anchors: the custom-agent router must not block the event loop.

The custom-agent handlers resolve the active store, access agent directories,
and may perform filesystem or database IO. Create/read/check/update/delete all
offload their complete blocking operations via ``asyncio.to_thread``; if any of
that work regresses onto the event loop, the strict Blockbuster gate raises
``BlockingError`` and these tests fail.

Imports live at module scope so the one-time FastAPI app construction (which
reads files while building OpenAPI schemas) happens at collection time, not on
the event loop under test. Test-side path resolution is itself offloaded with
``asyncio.to_thread`` (matching ``test_uploads_middleware``) so only the
handlers' own filesystem access is exercised on the loop.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from threading import get_ident
from types import SimpleNamespace
from unittest.mock import AsyncMock, call

import pytest
from fastapi import HTTPException

from app.gateway.routers import agents as agents_router
from app.gateway.routers.agents import (
    AgentCreateRequest,
    AgentUpdateRequest,
    check_agent_name,
    create_agent_endpoint,
    delete_agent,
    get_agent,
    list_agents,
    update_agent,
)
from deerflow.config.agents_api_config import load_agents_api_config_from_dict
from deerflow.config.agents_config import AgentConfig
from deerflow.config.app_config import reset_app_config
from deerflow.config.paths import get_paths
from deerflow.runtime.user_context import (
    WorkspaceStorageContext,
    get_effective_user_id,
    reset_current_user,
    reset_storage_context,
    set_current_user,
    set_storage_context,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _isolate_agent_store_config(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("DEER_FLOW_CONFIG_PATH", raising=False)
    monkeypatch.setenv("DEER_FLOW_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr("deerflow.config.app_config._legacy_config_candidates", lambda: ())


async def test_create_agent_does_not_block_event_loop(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    load_agents_api_config_from_dict({"enabled": True})
    try:
        response = await create_agent_endpoint(AgentCreateRequest(name="loop-make-agent", soul="You are a test agent."))
        assert response is not None

        user_id = get_effective_user_id()
        # test-side check (resolution offloaded; not exercised on the loop)
        agent_dir = await asyncio.to_thread(get_paths().user_agent_dir, user_id, "loop-make-agent")
        assert await asyncio.to_thread((agent_dir / "config.yaml").exists)
    finally:
        load_agents_api_config_from_dict({})


async def test_delete_agent_does_not_block_event_loop(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    load_agents_api_config_from_dict({"enabled": True})
    try:
        user_id = get_effective_user_id()
        user_id = get_effective_user_id()
        # test-side seeding (resolution offloaded; not exercised on the loop)
        agent_dir = await asyncio.to_thread(get_paths().user_agent_dir, user_id, "loop-test-agent")
        await asyncio.to_thread(agent_dir.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread((agent_dir / "config.yaml").write_text, "name: loop-test-agent\n", encoding="utf-8")

        await delete_agent("loop-test-agent")

        assert not await asyncio.to_thread(agent_dir.exists)
    finally:
        load_agents_api_config_from_dict({})


async def test_read_endpoints_do_not_block_event_loop(tmp_path: Path, monkeypatch) -> None:
    # list/get/check read through the sync agent store; on the db backend each is
    # a DB round trip. They must offload via asyncio.to_thread, or the strict
    # Blockbuster gate raises BlockingError here (finding: reads on the loop).
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    load_agents_api_config_from_dict({"enabled": True})
    try:
        await create_agent_endpoint(AgentCreateRequest(name="loop-read-agent", soul="You are a test agent."))

        listed = await list_agents()
        assert any(a.name == "loop-read-agent" for a in listed.agents)

        got = await get_agent("loop-read-agent")
        assert got.name == "loop-read-agent"

        check = await check_agent_name("loop-read-agent")
        assert check["available"] is False
        assert (await check_agent_name("never-created-agent"))["available"] is True
    finally:
        load_agents_api_config_from_dict({})


async def test_update_agent_does_not_block_event_loop(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    load_agents_api_config_from_dict({"enabled": True})
    try:
        await create_agent_endpoint(AgentCreateRequest(name="loop-update-agent", soul="Original soul"))

        response = await update_agent("loop-update-agent", AgentUpdateRequest(description="Updated description"))

        assert response.description == "Updated description"
    finally:
        load_agents_api_config_from_dict({})


async def _write_momobot_test_config(tmp_path: Path) -> None:
    config = """sandbox:
  use: deerflow.sandbox.local:LocalSandboxProvider
agents_api:
  enabled: true
momobot_max:
  enabled: true
  model: test-max-model
  base_model: test-base-model
  clients:
    - unlocked-client
"""
    await asyncio.to_thread((tmp_path / "config.yaml").write_text, config, encoding="utf-8")
    await asyncio.to_thread(reset_app_config)


def _record_app_config_threads(monkeypatch) -> tuple[int, list[int]]:
    loop_thread_id = get_ident()
    config_threads: list[int] = []
    original_get_app_config = agents_router.get_app_config

    def get_app_config_with_thread_record() -> object:
        config_threads.append(get_ident())
        return original_get_app_config()

    monkeypatch.setattr(agents_router, "get_app_config", get_app_config_with_thread_record)
    return loop_thread_id, config_threads


async def test_staff_agent_list_and_get_keep_actor_filtering_with_config_off_loop(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    await _write_momobot_test_config(tmp_path)
    load_agents_api_config_from_dict({"enabled": True})

    actor_id = "staff-actor"
    storage_user_id = "staff-storage-owner"
    user = SimpleNamespace(id=actor_id, system_role="user")
    user_token = set_current_user(user)
    storage_token = set_storage_context(WorkspaceStorageContext(actor_user_id=actor_id, organization_id="test-org", storage_user_id=storage_user_id, role="member"))
    loop_thread_id, config_threads = _record_app_config_threads(monkeypatch)
    visible_client_actor_ids: list[str] = []
    list_user_ids: list[str | None] = []
    loaded_agents: dict[str, AgentConfig] = {
        "visible-client-agent": AgentConfig(name="visible-client-agent", client_id="client-1"),
        "foreign-client-agent": AgentConfig(name="foreign-client-agent", client_id="client-2"),
        "unscoped-agent": AgentConfig(name="unscoped-agent"),
    }

    async def visible_clients(user_id: str) -> frozenset[str]:
        visible_client_actor_ids.append(user_id)
        return frozenset({"client-1"})

    def list_custom_agents(*, user_id: str | None = None) -> list[AgentConfig]:
        list_user_ids.append(user_id)
        return list(loaded_agents.values())

    def load_agent_config(name: str, *, user_id: str | None = None) -> AgentConfig | None:
        assert user_id == storage_user_id
        return loaded_agents.get(name)

    monkeypatch.setattr(agents_router, "_visible_client_ids", visible_clients)
    monkeypatch.setattr(agents_router, "list_custom_agents", list_custom_agents)
    monkeypatch.setattr(agents_router, "load_agent_config", load_agent_config)
    monkeypatch.setattr(agents_router, "load_agent_soul", lambda name, *, user_id=None: f"soul:{user_id}:{name}")

    try:
        listed = await list_agents()
        assert [agent.name for agent in listed.agents] == [agents_router.MOMOBOT_MAX_NAME, "visible-client-agent", "unscoped-agent"]
        assert listed.agents[0].builtin is True

        visible = await get_agent("visible-client-agent")
        assert visible.client_id == "client-1"
        assert visible.soul == f"soul:{storage_user_id}:visible-client-agent"

        with pytest.raises(HTTPException) as exc_info:
            await get_agent("foreign-client-agent")
        assert exc_info.value.status_code == 404

        assert list_user_ids == [storage_user_id]
        assert visible_client_actor_ids == [actor_id, actor_id, actor_id]
        assert config_threads and all(thread_id != loop_thread_id for thread_id in config_threads)
    finally:
        load_agents_api_config_from_dict({})
        await asyncio.to_thread(reset_app_config)
        reset_storage_context(storage_token)
        reset_current_user(user_token)


@pytest.mark.parametrize(
    ("actor_id", "client_keys", "expected_display_name"),
    [
        ("unlocked-client-actor", ("unlocked-client",), "MomoBot Max"),
        ("base-client-actor", ("base-client",), agents_router.MOMOBOT_BASE_DISPLAY_NAME),
    ],
)
async def test_client_agent_list_and_get_keep_tier_visibility_with_config_off_loop(
    tmp_path: Path,
    monkeypatch,
    actor_id: str,
    client_keys: tuple[str, ...],
    expected_display_name: str,
) -> None:
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    await _write_momobot_test_config(tmp_path)

    organization_id = "client-org"
    user = SimpleNamespace(id=actor_id, system_role="client")
    user_token = set_current_user(user)
    storage_token = set_storage_context(WorkspaceStorageContext(actor_user_id=actor_id, organization_id=organization_id, storage_user_id="client-storage-owner", role="client_contact"))
    loop_thread_id, config_threads = _record_app_config_threads(monkeypatch)
    visible_client_actor_ids: list[str] = []
    client_keys_for_user = AsyncMock(return_value=client_keys)

    async def visible_clients(user_id: str) -> frozenset[str]:
        visible_client_actor_ids.append(user_id)
        return frozenset({"unlocked-client"})

    monkeypatch.setattr(agents_router, "_visible_client_ids", visible_clients)
    monkeypatch.setattr("app.gateway.momobot_max.client_keys_for_user", client_keys_for_user)

    try:
        listed = await list_agents()
        assert [agent.name for agent in listed.agents] == [agents_router.MOMOBOT_MAX_NAME]
        assert listed.agents[0].display_name == expected_display_name
        assert listed.agents[0].model is None
        assert listed.agents[0].soul is None
        assert listed.agents[0].builtin is True

        fetched = await get_agent(agents_router.MOMOBOT_MAX_NAME)
        assert fetched.display_name == expected_display_name
        assert fetched.model is None
        assert fetched.soul is None
        assert fetched.builtin is True

        with pytest.raises(HTTPException) as exc_info:
            await get_agent("private-agent")
        assert exc_info.value.status_code == 404

        assert client_keys_for_user.await_args_list == [call(actor_id, organization_id)] * 3
        assert visible_client_actor_ids == [actor_id]
        assert len(config_threads) == 6
        assert all(thread_id != loop_thread_id for thread_id in config_threads)
    finally:
        await asyncio.to_thread(reset_app_config)
        reset_storage_context(storage_token)
        reset_current_user(user_token)
