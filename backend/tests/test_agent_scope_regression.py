"""Copy into backend/tests to run; only synthetic identity and mocked storage."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.csrf_middleware import CSRFMiddleware
from app.gateway.routers import agents
from deerflow.config.agents_config import AgentConfig
from deerflow.config.authorization_config import AuthorizationConfig
from deerflow.persistence.organizations.resolution import ActiveOrganization


@pytest.mark.parametrize("scope, expected_status", [("threads:read", 403), ("threads:write", 201)])
def test_agent_creation_requires_write_scope(monkeypatch, scope, expected_status):
    monkeypatch.delenv("DEER_FLOW_AUTH_DISABLED", raising=False)
    user = SimpleNamespace(id="audit-user", system_role="user")
    org = ActiveOrganization(id="audit-org", name="Audit", role="member", storage_user_id="audit-storage")
    monkeypatch.setattr("app.gateway.auth.pat.authenticate_pat", AsyncMock(return_value=(user, frozenset({scope}), org.id)))
    monkeypatch.setattr("app.gateway.auth_middleware._resolve_active_workspace", AsyncMock(return_value=org))
    monkeypatch.setattr("app.gateway.authz._get_route_authorization_config", lambda: AuthorizationConfig())
    monkeypatch.setattr("deerflow.config.app_config.get_app_config", lambda: SimpleNamespace(private_workspace=SimpleNamespace(enabled=True)))
    monkeypatch.setattr(agents, "get_agents_api_config", lambda: SimpleNamespace(enabled=True))
    store = MagicMock()
    monkeypatch.setattr(agents, "get_agent_store", lambda: store)
    monkeypatch.setattr(agents, "load_agent_config", lambda *a, **kw: AgentConfig(name="read-token-agent"))
    monkeypatch.setattr(agents, "load_agent_soul", lambda *a, **kw: "")
    app = FastAPI()
    app.include_router(agents.router)
    app.add_middleware(AuthMiddleware)
    app.add_middleware(CSRFMiddleware)
    with TestClient(app) as client:
        response = client.post("/api/agents", headers={"Authorization": "Bearer synthetic-offline-test"}, json={"name": "read-token-agent", "soul": "Synthetic audit"})
    assert response.status_code == expected_status
    assert store.create.call_count == (1 if expected_status == 201 else 0)
