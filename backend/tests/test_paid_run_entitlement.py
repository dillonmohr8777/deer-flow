"""Admission gates delegate to the integration lane without widening old-base auth."""

from __future__ import annotations

import functools
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.gateway import authz, paid_run_entitlement
from app.gateway.authz import AuthContext

ADMISSIONS = [
    ("openai_agents", "/api/openai-agents/sessions", "create", {"input": "Task"}),
    ("openai_agents", "/api/openai-agents/sessions/local/messages", "message", {"input": "Task"}),
    ("browserbase_research", "/api/browserbase/research", "create", {"urls": ["https://example.com/"]}),
]


def _old_base(monkeypatch):
    monkeypatch.delattr(authz, "require_entitlement", raising=False)
    monkeypatch.setattr(paid_run_entitlement.importlib.util, "find_spec", lambda name: None)


def _app(monkeypatch, module_name):
    """Load a fresh router without mutating the collected production router module."""
    source = Path(__file__).resolve().parents[1] / "app/gateway/routers" / f"{module_name}.py"
    name = f"test_entitlement_router_{module_name}"
    spec = importlib.util.spec_from_file_location(name, source)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    service = SimpleNamespace(create=AsyncMock(return_value={"id": "local"}), message=AsyncMock(return_value={"id": "local"}))
    monkeypatch.setattr(module, "_service", lambda request: service)
    app = FastAPI()

    @app.middleware("http")
    async def identity(request, call_next):
        request.state.auth = AuthContext(
            user=SimpleNamespace(id="alice"),
            permissions=request.headers.get("test-permissions", "runs:create").split(","),
            actor_user_id="alice",
            organization_id="org-a",
            storage_user_id="shared-storage",
        )
        return await call_next(request)

    app.include_router(module.router)
    return app, service, module


def _scope_headers(app, module_name, module):
    from starlette.requests import Request

    request = Request({"type": "http", "app": app})
    request.state.auth = AuthContext(user=SimpleNamespace(id="alice"), actor_user_id="alice", organization_id="org-a", storage_user_id="shared-storage")
    scope = module._owner(request) if module_name == "openai_agents" else module._identity(request)[1]
    header = "X-Expected-Agent-Scope" if module_name == "openai_agents" else "X-Expected-Browserbase-Scope"
    return {header: scope, "Idempotency-Key": "receipt"}


@pytest.mark.parametrize(("module_name", "path", "method", "payload"), ADMISSIONS)
@pytest.mark.parametrize("reason", ["missing", "suspended"])
def test_modern_entitlement_denial_precedes_provider(monkeypatch, module_name, path, method, payload, reason):
    calls = []

    def require_entitlement(key):
        assert key == "runs.create"

        def decorate(func):
            @functools.wraps(func)
            async def gate(*args, **kwargs):
                auth = kwargs["request"].state.auth
                calls.append((key, auth.actor_user_id, auth.organization_id))
                raise HTTPException(403, detail={"error": "entitlement_exceeded", "key": key, "reason": reason})

            return gate

        return decorate

    monkeypatch.setattr(authz, "require_entitlement", require_entitlement, raising=False)
    app, service, module = _app(monkeypatch, module_name)
    with TestClient(app) as client:
        response = client.post(path, headers=_scope_headers(app, module_name, module), json=payload)
    assert response.status_code == 403
    assert response.json()["detail"] == {"error": "entitlement_exceeded", "key": "runs.create", "reason": reason}
    assert calls == [("runs.create", "alice", "org-a")]
    service.create.assert_not_awaited()
    service.message.assert_not_awaited()


@pytest.mark.parametrize(("module_name", "path", "method", "payload"), ADMISSIONS)
def test_old_base_preserves_permission_and_workspace_fences(monkeypatch, module_name, path, method, payload):
    _old_base(monkeypatch)
    app, service, module = _app(monkeypatch, module_name)
    headers = _scope_headers(app, module_name, module)
    with TestClient(app) as client:
        denied = client.post(path, headers={**headers, "test-permissions": "runs:read"}, json=payload)
        assert denied.status_code == 403
        scope_header = next(key for key in headers if key.startswith("X-Expected"))
        stale = client.post(path, headers={**headers, scope_header: "stale"}, json=payload)
        assert stale.status_code == 409
        service.create.assert_not_awaited()
        service.message.assert_not_awaited()
        accepted = client.post(path, headers=headers, json=payload)
    assert accepted.status_code == 200
    getattr(service, method).assert_awaited_once()


def test_permission_guard_runs_before_modern_entitlement(monkeypatch):
    calls = []

    def require_entitlement(key):
        def decorate(func):
            @functools.wraps(func)
            async def gate(*args, **kwargs):
                calls.append(key)
                return await func(*args, **kwargs)

            return gate

        return decorate

    monkeypatch.setattr(authz, "require_entitlement", require_entitlement, raising=False)
    app, service, module = _app(monkeypatch, "openai_agents")
    headers = {**_scope_headers(app, "openai_agents", module), "test-permissions": "runs:read"}
    with TestClient(app) as client:
        assert client.post("/api/openai-agents/sessions", headers=headers, json={"input": "Task"}).status_code == 403
    assert not calls
    service.create.assert_not_awaited()


@pytest.mark.parametrize("module_name", ["deerflow.config.entitlement_config", "deerflow.authz.entitlements", "deerflow.persistence.entitlements"])
def test_partial_entitlement_installation_fails_closed(monkeypatch, module_name):
    monkeypatch.delattr(authz, "require_entitlement", raising=False)
    monkeypatch.setattr(paid_run_entitlement.importlib.util, "find_spec", lambda name: object() if name == module_name else None)
    with pytest.raises(RuntimeError, match="entitlement"):
        paid_run_entitlement.require_paid_run_entitlement(AsyncMock())


@pytest.mark.parametrize("factory", [None, "invalid", lambda key: None, lambda key: lambda func: None, lambda key: lambda func: lambda: None])
def test_invalid_existing_entitlement_gate_fails_closed(monkeypatch, factory):
    monkeypatch.setattr(authz, "require_entitlement", factory, raising=False)
    with pytest.raises(TypeError, match="entitlement"):
        paid_run_entitlement.require_paid_run_entitlement(AsyncMock())


@pytest.mark.asyncio
async def test_modern_gate_runtime_failure_is_not_swallowed(monkeypatch):
    def require_entitlement(key):
        def decorate(func):
            async def gate(*args, **kwargs):
                raise RuntimeError("entitlement storage unavailable")

            return gate

        return decorate

    monkeypatch.setattr(authz, "require_entitlement", require_entitlement, raising=False)
    target = AsyncMock()
    gated = paid_run_entitlement.require_paid_run_entitlement(target)
    with pytest.raises(RuntimeError, match="entitlement storage unavailable"):
        await gated()
    target.assert_not_awaited()
