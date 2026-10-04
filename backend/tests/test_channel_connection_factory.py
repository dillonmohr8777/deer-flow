"""Production channel repository factories share optional credential encryption."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from starlette.requests import Request

from app.channels.service import _make_connection_repo
from app.gateway.routers.channel_connections import _get_repository
from deerflow.config.channel_connections_config import ChannelConnectionsConfig
from deerflow.persistence.channel_connections import ChannelCredentialRow

_KEY_ENV = "CHANNEL_CONNECTIONS_ENCRYPTION_KEY"
_TEST_KEY = "synthetic-test-only-channel-encryption-key"


@pytest.fixture
async def database(tmp_path, monkeypatch):
    from deerflow.persistence.engine import close_engine, init_engine

    monkeypatch.delenv(_KEY_ENV, raising=False)
    await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'channels.db'}", sqlite_dir=str(tmp_path))
    try:
        yield
    finally:
        await close_engine()


def service_repo():
    return _make_connection_repo(ChannelConnectionsConfig(enabled=True))


def router_repo():
    return _get_repository(Request({"type": "http", "app": FastAPI()}), ChannelConnectionsConfig(enabled=True))


@pytest.mark.anyio
@pytest.mark.parametrize("writer_factory,reader_factory", [(service_repo, router_repo), (router_repo, service_repo)])
async def test_configured_factories_share_encrypted_sql_credentials(database, monkeypatch, writer_factory, reader_factory):
    monkeypatch.setenv(_KEY_ENV, _TEST_KEY)
    writer = writer_factory()
    connection = await writer.upsert_connection(owner_user_id="alice", provider="slack", external_account_id="U1", workspace_id="T1")
    await writer.store_credentials(connection["id"], access_token="synthetic-access-token", refresh_token="synthetic-refresh-token", extra={"bot_user_id": "B-synthetic-bot-identity"})

    async with writer.session_factory() as session:
        row = await session.get(ChannelCredentialRow, connection["id"])
        assert row.encrypted_access_token.startswith("fernet:v1:")
        assert "synthetic-access-token" not in row.encrypted_access_token
        assert "synthetic-refresh-token" not in row.encrypted_refresh_token
        assert "B-synthetic-bot-identity" not in row.encrypted_extra_json

    reader = reader_factory()
    credentials = await reader.get_credentials(connection["id"], owner_user_id="alice")
    assert credentials["access_token"] == "synthetic-access-token"
    assert credentials["refresh_token"] == "synthetic-refresh-token"
    assert credentials["extra"] == {"bot_user_id": "B-synthetic-bot-identity"}
    assert await reader.get_credentials(connection["id"], owner_user_id="bob") is None


@pytest.mark.anyio
@pytest.mark.parametrize("factory", [service_repo, router_repo])
@pytest.mark.parametrize("key", [None, "", " \t "])
async def test_without_key_factories_keep_identity_binding_but_refuse_credentials(database, monkeypatch, factory, key):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "synthetic-operator-token-not-an-encryption-key")
    if key is not None:
        monkeypatch.setenv(_KEY_ENV, key)
    repo = factory()
    connection = await repo.upsert_connection(owner_user_id="alice", provider="slack", external_account_id="U1", workspace_id="T1")
    assert (await repo.list_connections("alice"))[0]["id"] == connection["id"]
    with pytest.raises(RuntimeError, match="encryption key is required"):
        await repo.store_credentials(connection["id"], access_token="synthetic-access-token")
    assert await repo.get_credentials(connection["id"], owner_user_id="alice") is None


@pytest.mark.anyio
@pytest.mark.parametrize("factory", [service_repo, router_repo])
@pytest.mark.parametrize("replacement_key", [None, "different-synthetic-key"])
async def test_missing_or_changed_key_cannot_read_existing_encrypted_rows(database, monkeypatch, factory, replacement_key, caplog):
    monkeypatch.setenv(_KEY_ENV, _TEST_KEY)
    writer = service_repo()
    connection = await writer.upsert_connection(owner_user_id="alice", provider="slack", external_account_id="U1", workspace_id="T1")
    await writer.store_credentials(connection["id"], access_token="synthetic-access-token")
    if replacement_key is None:
        monkeypatch.delenv(_KEY_ENV)
    else:
        monkeypatch.setenv(_KEY_ENV, replacement_key)
    assert await factory().get_credentials(connection["id"], owner_user_id="alice") is None
    assert "synthetic-access-token" not in caplog.text
    assert _TEST_KEY not in caplog.text


def test_service_factory_remains_disabled_without_configuration():
    assert _make_connection_repo(None) is None
    assert _make_connection_repo(SimpleNamespace(enabled=False)) is None


@pytest.mark.anyio
async def test_router_preserves_injected_repository(database, monkeypatch):
    monkeypatch.setenv(_KEY_ENV, _TEST_KEY)
    repo = service_repo()
    app = FastAPI()
    app.state.channel_connection_repo = repo
    monkeypatch.delenv(_KEY_ENV)
    assert _get_repository(Request({"type": "http", "app": app}), ChannelConnectionsConfig(enabled=True)) is repo
