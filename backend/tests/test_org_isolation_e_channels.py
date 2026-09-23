"""M3 lane E: channel connections, connect codes and conversations never cross organizations.

Channels stay personal during M3 (decision 4): a connection, its pending connect
codes (``channel_oauth_states``) and its conversations live in the owner's
private organization. Browser routes filter by the active organization, so from
another organization, or from a shared workspace, they answer as if nothing
exists. Header-only internal calls keep working in this phase.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import FastAPI
from org_isolation_fixtures import ORG_A, ORG_B, ORG_C, ORG_S, STORAGE_S, USER_A, USER_B, USER_C, auth_headers, org_world  # noqa: F401
from sqlalchemy import select, update

from app.channels.connection_identity import attach_connection_identity
from app.channels.manager import BOUND_IDENTITY_REQUIRED_MESSAGE, ChannelManager
from app.channels.message_bus import InboundMessage, MessageBus
from app.channels.runtime_config_store import ChannelRuntimeConfigStore
from app.channels.store import ChannelStore
from app.channels.telegram import TelegramChannel
from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.internal_auth import create_internal_auth_headers
from app.gateway.routers import channel_connections
from deerflow.config.channel_connections_config import ChannelConnectionsConfig
from deerflow.persistence.channel_connections import ChannelConnectionRepository, ChannelOAuthStateRow
from deerflow.persistence.organizations.delegation import OrganizationDelegationRepository
from deerflow.persistence.thread_meta.model import ThreadMetaRow


def _app(session_factory, tmp_path) -> FastAPI:
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.state.channel_connections_config = ChannelConnectionsConfig.model_validate({"enabled": True, "telegram": {"enabled": True, "bot_username": "deerflow_bot"}})
    app.state.channels_config = {"telegram": {"enabled": True, "bot_token": "telegram-token"}}
    app.state.channel_runtime_config_store = ChannelRuntimeConfigStore(tmp_path / "runtime-config.json")
    app.state.channel_connection_repo = ChannelConnectionRepository(session_factory)
    app.include_router(channel_connections.router)
    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _resolve(delegations: OrganizationDelegationRepository, connection_id: str, organization_id: str):
    return await delegations.resolve_active_delegation(subject_type="channel_connection", subject_id=connection_id, organization_id=organization_id, scope="runs:create")


def _telegram_update(*, user_id: int):
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_user.username = f"user{user_id}"
    update.effective_user.full_name = f"User {user_id}"
    update.effective_chat.id = 100
    update.effective_chat.type = "private"
    update.message.reply_text = AsyncMock()
    return update


@pytest.mark.asyncio
async def test_connections_are_not_found_from_another_organization(org_world, tmp_path):  # noqa: F811
    repo = ChannelConnectionRepository(org_world)
    connection = await repo.upsert_connection(owner_user_id=USER_A, provider="telegram", external_account_id="tg-a", workspace_id="chat-a")
    assert connection["organization_id"] == ORG_A

    async with _client(_app(org_world, tmp_path)) as client:
        # Organization B, and a acting in shared workspace S, cannot see or disconnect a's personal connection.
        for headers in (auth_headers(USER_B), auth_headers(USER_A, ORG_S)):
            listed = await client.get("/api/channels/connections", headers=headers)
            assert (listed.status_code, listed.json()) == (200, {"connections": []})
            providers = await client.get("/api/channels/providers", headers=headers)
            assert [provider["connection_status"] for provider in providers.json()["providers"]] == ["not_connected"]
            assert (await client.delete(f"/api/channels/connections/{connection['id']}", headers=headers)).status_code == 404

        # Header-only internal calls carry no organization and keep their user filter in this phase.
        internal = await client.get("/api/channels/connections", headers=create_internal_auth_headers(owner_user_id=USER_A))
        assert [item["id"] for item in internal.json()["connections"]] == [connection["id"]]

        listed = await client.get("/api/channels/connections", headers=auth_headers(USER_A))
        assert [(item["id"], item["status"]) for item in listed.json()["connections"]] == [(connection["id"], "connected")]
        assert (await client.delete(f"/api/channels/connections/{connection['id']}", headers=auth_headers(USER_A))).status_code == 204


@pytest.mark.asyncio
async def test_connect_codes_are_issued_only_in_the_owners_private_organization(org_world, tmp_path):  # noqa: F811
    async with _client(_app(org_world, tmp_path)) as client:
        assert (await client.post("/api/channels/telegram/connect", headers=auth_headers(USER_A, ORG_S))).status_code == 404
        assert (await client.post("/api/channels/telegram/connect", headers=auth_headers(USER_A))).status_code == 200

    async with org_world() as session:
        states = (await session.execute(select(ChannelOAuthStateRow))).scalars().all()
    assert [(state.owner_user_id, state.organization_id) for state in states] == [(USER_A, ORG_A)]


@pytest.mark.asyncio
async def test_connect_code_completes_only_into_the_organization_it_was_created_in(org_world):  # noqa: F811
    repo = ChannelConnectionRepository(org_world)
    expires_at = datetime.now(UTC) + timedelta(minutes=10)
    for state, owner in (("code-a", USER_A), ("code-slack-a", USER_A), ("code-org-a-for-b", USER_B), ("code-s-for-a", USER_A)):
        await repo.create_oauth_state(owner_user_id=owner, provider="slack" if state == "code-slack-a" else "telegram", state=state, expires_at=expires_at)
    # Codes recorded in an organization their owner's connection cannot live in: one created
    # in org A that would complete for b (org B), one created in shared workspace S for a.
    async with org_world() as session, session.begin():
        for state, organization_id in (("code-org-a-for-b", ORG_A), ("code-s-for-a", ORG_S)):
            await session.execute(update(ChannelOAuthStateRow).where(ChannelOAuthStateRow.state_hash == repo.hash_state(state)).values(organization_id=organization_id))

    channel = TelegramChannel(bus=MessageBus(), config={"bot_token": "test-token", "connection_repo": repo})
    for state in ("code-org-a-for-b", "code-s-for-a"):
        refused = _telegram_update(user_id=7)
        assert await channel._bind_connection_from_start_token_on_main(refused, state) is True
        refused.message.reply_text.assert_awaited_once_with("Telegram connection link is invalid or expired.")
    assert await repo.list_connections(USER_A) == []
    assert await repo.list_connections(USER_B) == []

    # A code completes into the organization it was created in, and says which.
    consumed = await repo.consume_oauth_state(provider="slack", state="code-slack-a")
    assert (consumed["owner_user_id"], consumed["organization_id"]) == (USER_A, ORG_A)
    assert await channel._bind_connection_from_start_token_on_main(_telegram_update(user_id=42), "code-a") is True
    assert [item["organization_id"] for item in await repo.list_connections(USER_A)] == [ORG_A]


@pytest.mark.asyncio
async def test_channel_conversation_cannot_point_at_another_owners_or_organizations_thread(org_world):  # noqa: F811
    repo = ChannelConnectionRepository(org_world)
    connection = await repo.upsert_connection(owner_user_id=USER_A, provider="slack", external_account_id="U-a", workspace_id="T1")
    async with org_world() as session, session.begin():
        session.add_all(
            [
                ThreadMetaRow(thread_id="thread-a", user_id=USER_A, organization_id=ORG_A),
                ThreadMetaRow(thread_id="thread-b", user_id=USER_B, organization_id=ORG_B),
                ThreadMetaRow(thread_id="thread-s", user_id=STORAGE_S, organization_id=ORG_S),
                ThreadMetaRow(thread_id="thread-ownerless", user_id=None, organization_id=None),
                ThreadMetaRow(thread_id="thread-a-stamped-s", user_id=USER_A, organization_id=ORG_S),
            ]
        )
    conversation = {"connection_id": connection["id"], "owner_user_id": USER_A, "provider": "slack"}
    await repo.set_thread_id(**conversation, external_conversation_id="C-own", thread_id="thread-a")

    for thread_id in ("thread-b", "thread-s", "thread-ownerless", "thread-a-stamped-s"):
        # Neither re-point the existing conversation nor attach a new one.
        for external_conversation_id in ("C-own", "C-new"):
            with pytest.raises(ValueError):
                await repo.set_thread_id(**conversation, external_conversation_id=external_conversation_id, thread_id=thread_id)

    assert await repo.get_thread_id(connection["id"], "C-own") == "thread-a"
    assert await repo.get_thread_id(connection["id"], "C-new") is None


@pytest.mark.asyncio
async def test_disconnect_revokes_the_connection_delegation_and_refuses_the_next_message(org_world, tmp_path):  # noqa: F811
    repo = ChannelConnectionRepository(org_world)
    delegations = OrganizationDelegationRepository(org_world)
    connection = await repo.upsert_connection(owner_user_id=USER_A, provider="slack", external_account_id="U-a", workspace_id="T1")
    await delegations.grant(organization_id=ORG_A, subject_type="channel_connection", subject_id=connection["id"], owner_user_id=USER_A, scopes=["runs:create"])
    assert await _resolve(delegations, connection["id"], ORG_A) is not None

    async with _client(_app(org_world, tmp_path)) as client:
        assert (await client.delete(f"/api/channels/connections/{connection['id']}", headers=auth_headers(USER_A))).status_code == 204
    assert await _resolve(delegations, connection["id"], ORG_A) is None

    # The next message from that identity no longer resolves to the connection, and one queued
    # before the disconnect, still carrying it, is refused too: neither reaches a thread or a run.
    fresh = await attach_connection_identity(InboundMessage(channel_name="slack", chat_id="C1", user_id="U-a", text="hi"), repo=repo, provider="slack", workspace_id="T1")
    assert fresh.connection_id is None
    stale = InboundMessage(channel_name="slack", chat_id="C1", user_id="U-a", text="hi", connection_id=connection["id"], owner_user_id=USER_A, workspace_id="T1")
    bus = MessageBus()
    outbound = []

    async def capture(message):
        outbound.append(message)

    bus.subscribe_outbound(capture)
    manager = ChannelManager(bus=bus, store=ChannelStore(path=tmp_path / "store.json"), connection_repo=repo, require_bound_identity=True)
    manager._client = gateway = MagicMock()
    for message in (fresh, stale):
        await manager._handle_message(message)

    assert [message.text for message in outbound] == [BOUND_IDENTITY_REQUIRED_MESSAGE] * 2
    gateway.threads.create.assert_not_called()
    gateway.runs.wait.assert_not_called()


@pytest.mark.asyncio
async def test_ownership_transfer_and_provider_removal_revoke_connection_delegations(org_world):  # noqa: F811
    repo = ChannelConnectionRepository(org_world)
    delegations = OrganizationDelegationRepository(org_world)
    slack = await repo.upsert_connection(owner_user_id=USER_A, provider="slack", external_account_id="U-shared", workspace_id="T1")
    telegram = await repo.upsert_connection(owner_user_id=USER_C, provider="telegram", external_account_id="tg-c")
    for owner, organization_id, connection in ((USER_A, ORG_A, slack), (USER_C, ORG_C, telegram)):
        await delegations.grant(organization_id=organization_id, subject_type="channel_connection", subject_id=connection["id"], owner_user_id=owner, scopes=["runs:create"])
        assert await _resolve(delegations, connection["id"], organization_id) is not None

    # b binds the Slack identity a had bound: a's connection transfers away, and its delegation with it.
    await repo.upsert_connection(owner_user_id=USER_B, provider="slack", external_account_id="U-shared", workspace_id="T1")
    assert await _resolve(delegations, slack["id"], ORG_A) is None

    # An operator removing a provider revokes the delegation of every connection it revokes.
    assert await repo.disconnect_provider_connections(provider="telegram") == 1
    assert await _resolve(delegations, telegram["id"], ORG_C) is None
