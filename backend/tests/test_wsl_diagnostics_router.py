"""Real router/decorator admission with mocked existing thread operations."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from test_wsl_bridge import enqueue, receipt

from app.gateway import wsl_bridge_attachment as attachment
from app.gateway.authz import AuthContext
from app.gateway.routers import wsl_diagnostics as routes
from app.gateway.wsl_bridge import BridgeError


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("MOMO_WSL_BRIDGE_ENABLED", "true")
    monkeypatch.setenv("MOMO_WSL_BRIDGE_ROOT", str(tmp_path.resolve()))
    return routes.BridgeStore.from_environment()


@pytest.fixture
def app(store, monkeypatch, tmp_path):
    app = FastAPI()
    app.include_router(routes.router)
    app.state.thread_store = SimpleNamespace(check_access=AsyncMock(return_value=True))
    app.state.test_identity = dict(actor="actor", org="org", storage="storage", source="session", role="user", delegation=None)
    app.state.write_count = 0
    app.state.operation_count = 0

    @asynccontextmanager
    async def reserve(thread_id, *, kind, user_id):
        assert (thread_id, user_id, kind.value) == ("thread", "storage", "artifact_write")
        app.state.operation_count += 1
        yield

    app.state.run_manager = SimpleNamespace(reserve_thread_operation=reserve)

    @app.middleware("http")
    async def authenticate(request, call_next):
        identity = app.state.test_identity
        user = SimpleNamespace(id=identity["actor"], system_role=identity["role"])
        request.state.auth = AuthContext(user=user, permissions=["threads:read", "threads:write"], organization_id=identity["org"], actor_user_id=identity["actor"], storage_user_id=identity["storage"])
        request.state.user = user
        request.state.auth_source = identity["source"]
        request.state.delegation_id = identity["delegation"]
        request.state.storage_user_id = identity["storage"]
        return await call_next(request)

    def attach(path, content):
        assert path.name.startswith("wsl-diagnostic-momo-")
        assert json.loads(content)["stdout_b64"] == "TGludXgK"
        app.state.write_count += 1

    monkeypatch.setattr(attachment, "_attach_fixed_file", attach)
    monkeypatch.setattr(attachment, "_attachment_path", lambda store, job_id, thread_id, user_id: tmp_path / f"wsl-diagnostic-{job_id}.json")
    return app


def body(**changes):
    return {"request_id": "request", "argv": ["/usr/bin/uname", "-s"], "timeout": 30, **changes}


def test_gateway_registers_routes_without_enabling_or_starting_bridge(monkeypatch):
    from app.gateway.app import create_app

    monkeypatch.delenv("MOMO_WSL_BRIDGE_ENABLED", raising=False)
    paths = {route.path for route in create_app().routes}
    assert "/api/threads/{thread_id}/wsl-diagnostics" in paths
    assert "/api/threads/{thread_id}/wsl-diagnostics/{job_id}" in paths
    assert "/api/threads/{thread_id}/wsl-diagnostics/{job_id}/receipt" in paths


@pytest.mark.asyncio
async def test_authenticated_enqueue_existing_thread_and_readback(app, store):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/api/threads/thread/wsl-diagnostics", json=body())
        assert created.status_code == 200, created.text
        job_id = created.json()["job_id"]
        duplicate = await client.post("/api/threads/thread/wsl-diagnostics", json=body())
        assert duplicate.json() == created.json()
        status = await client.get(f"/api/threads/thread/wsl-diagnostics/{job_id}")
        assert status.json() == created.json()
        assert app.state.operation_count == app.state.write_count == 0
        app.state.thread_store.check_access.assert_awaited_with("thread", "storage", require_existing=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", [{"actor": "foreign"}, {"org": "foreign"}, {"storage": "foreign"}])
async def test_foreign_binding_denied_even_with_shared_storage_access(app, store, changed):
    job = enqueue(store)["job"]
    app.state.test_identity.update(changed)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get(f"/api/threads/thread/wsl-diagnostics/{job['id']}")).status_code == 404
        assert (await client.get(f"/api/threads/other/wsl-diagnostics/{job['id']}")).status_code == 404
    assert app.state.write_count == app.state.operation_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("extra", [{"actor_user_id": "forged"}, {"organization_id": "forged"}, {"storage_user_id": "forged"}, {"timeout": True}, {"argv": ["/bin/sh", "-c"]}])
async def test_public_payload_cannot_control_identity_or_command(app, store, extra):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        result = await client.post("/api/threads/thread/wsl-diagnostics", json=body(**extra))
        assert result.status_code == 422
    assert not store.path.exists()


@pytest.mark.asyncio
async def test_receipt_requires_verified_internal_boundary_and_attaches_once(app, store):
    job = enqueue(store)["job"]
    store.claim()
    url = f"/api/threads/thread/wsl-diagnostics/{job['id']}/receipt"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.post(url, json={"receipt": receipt(job)})).status_code == 403
        app.state.test_identity.update(source="internal", role="internal")
        assert (await client.post(url, json={"receipt": receipt(job)})).status_code == 403
        app.state.test_identity.update(delegation="verified-delegation")
        first = await client.post(url, json={"receipt": receipt(job)})
        assert first.status_code == 200, first.text
        assert first.json()["attached"] is True
        assert (await client.post(url, json={"receipt": receipt(job)})).json() == first.json()
        read = await client.get(url.removesuffix("/receipt"))
        assert read.json()["receipt"]["stdout_b64"] == "TGludXgK"
    assert app.state.write_count == app.state.operation_count == 1


@pytest.mark.asyncio
async def test_missing_thread_disabled_auth_and_foreign_callback_fail_closed(app, store):
    job = enqueue(store)["job"]
    store.claim()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        app.state.thread_store.check_access.return_value = False
        assert (await client.post("/api/threads/thread/wsl-diagnostics", json=body())).status_code == 404
        app.state.thread_store.check_access.return_value = True
        app.state.test_identity.update(source="auth_disabled", role="admin")
        assert (await client.post("/api/threads/thread/wsl-diagnostics", json=body())).status_code == 403
        app.state.test_identity.update(source="internal", role="internal", delegation="verified-delegation", actor="foreign")
        assert (await client.post(f"/api/threads/thread/wsl-diagnostics/{job['id']}/receipt", json={"receipt": receipt(job)})).status_code == 404
    assert store.status(job["id"])["state"] == "claimed"
    assert app.state.write_count == 0


@pytest.mark.asyncio
async def test_async_route_offloads_spool_io(app, store, monkeypatch):
    owner_thread = __import__("threading").get_ident()
    original = type(store).enqueue

    def checked(self, **kwargs):
        assert __import__("threading").get_ident() != owner_thread
        return original(self, **kwargs)

    monkeypatch.setattr(type(store), "enqueue", checked)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.post("/api/threads/thread/wsl-diagnostics", json=body())).status_code == 200


@pytest.mark.asyncio
async def test_local_callback_uses_same_validation_and_origin_authorization(store, monkeypatch):
    job = enqueue(store)["job"]
    store.claim()
    thread_store = SimpleNamespace(check_access=AsyncMock(return_value=False))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(thread_store=thread_store)))

    @asynccontextmanager
    async def local_request(record):
        yield request

    monkeypatch.setattr(attachment, "_local_request", local_request)
    with pytest.raises(BridgeError):
        await attachment.ingest_local_receipt(store, job["id"], receipt(job))
    assert store.read(job["id"])["receipt"] is None
    thread_store.check_access.return_value = True
    attached = AsyncMock(return_value={"attached": True})
    monkeypatch.setattr(attachment, "attach_receipt", attached)
    assert await attachment.ingest_local_receipt(store, job["id"], receipt(job)) == {"attached": True}
    attached.assert_awaited_once()
