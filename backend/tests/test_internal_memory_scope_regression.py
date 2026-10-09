"""Synthetic delegated internal caller; no real credentials or storage."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.csrf_middleware import CSRFMiddleware
from app.gateway.routers import memory
from deerflow.config.authorization_config import AuthorizationConfig
from deerflow.persistence.organizations.delegation import ActiveDelegation
from deerflow.persistence.organizations.resolution import ActiveOrganization


@pytest.mark.parametrize("scope,expected", [("runs:create", 403), ("threads:read", 403), ("threads:write", 403), ("threads:delete", 200)])
def test_memory_clear_requires_delete_scope(monkeypatch, scope, expected):
    monkeypatch.delenv("DEER_FLOW_AUTH_DISABLED", raising=False)
    org = ActiveOrganization(id="audit-org", name="Audit", role="member", storage_user_id="audit-storage")
    delegation = ActiveDelegation(id="audit-delegation", organization=org, subject_type="scheduled_task", subject_id="audit-task", owner_user_id="audit-user", scopes=frozenset({scope}))
    monkeypatch.setattr("app.gateway.auth_middleware.is_valid_internal_auth_token", lambda token: token == "synthetic-internal")
    monkeypatch.setattr("app.gateway.auth_middleware._resolve_internal_delegation", AsyncMock(return_value=delegation))
    monkeypatch.setattr("app.gateway.authz._get_route_authorization_config", lambda: AuthorizationConfig())
    manager = MagicMock()
    manager.clear_memory.return_value = {}
    monkeypatch.setattr(memory, "get_memory_manager", lambda: manager)
    app = FastAPI()
    app.include_router(memory.router)
    app.add_middleware(AuthMiddleware)
    app.add_middleware(CSRFMiddleware)
    with TestClient(app) as client:
        client.cookies.set("csrf_token", "synthetic-csrf")
        response = client.delete("/api/memory", headers={"X-DeerFlow-Internal-Token": "synthetic-internal", "X-DeerFlow-Delegation-Id": "audit-delegation", "X-CSRF-Token": "synthetic-csrf"})
    assert response.status_code == expected
    assert manager.clear_memory.call_count == (1 if expected == 200 else 0)
