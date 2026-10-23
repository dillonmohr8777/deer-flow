"""The `client` role reaches chat and nothing else, whatever the authorization config says."""

from __future__ import annotations

import os
import re
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from starlette.testclient import TestClient

os.environ.setdefault("AUTH_JWT_SECRET", "test-secret-key-client-route-boundary-min-32")

from app.gateway.auth_middleware import AuthMiddleware  # noqa: E402
from app.gateway.client_boundary import _RULES, is_client_allowed_route  # noqa: E402
from deerflow.config.authorization_config import AuthorizationConfig  # noqa: E402
from deerflow.persistence.organizations.identity import private_organization_id  # noqa: E402

# What a client may reach among the registered routes. Adding a line here is the
# review point for widening what an external customer can call.
CLIENT_REACHABLE_ROUTES = [
    "DELETE /api/threads/{thread_id}",
    "DELETE /api/threads/{thread_id}/goal",
    "DELETE /api/threads/{thread_id}/runs/{run_id}/feedback",
    "DELETE /api/threads/{thread_id}/runs/{run_id}/feedback/{feedback_id}",
    "DELETE /api/threads/{thread_id}/uploads/{filename}",
    "GET /api/workspaces",
    "GET /api/client-portal/clients",
    "GET /api/client-portal/threads",
    "GET /api/client-portal/threads/{thread_id}",
    "GET /api/client-portal/threads/{thread_id}/messages/{message_id}/attachments/{name}",
    "GET /api/agents",
    "GET /api/agents/{name}",
    "GET /api/features",
    "GET /api/models",
    "GET /api/models/{model_name}",
    "GET /api/momobot-brand/about",
    "GET /api/momobot-brand/assets/{path:path}",
    "GET /api/momobot-brand/kit",
    "GET /api/runs/{run_id}/feedback",
    "GET /api/runs/{run_id}/messages",
    "GET /api/suggestions/config",
    "GET /api/threads/{thread_id}",
    "GET /api/threads/{thread_id}/artifacts/{path:path}",
    "GET /api/threads/{thread_id}/goal",
    "GET /api/threads/{thread_id}/messages",
    "GET /api/threads/{thread_id}/messages/page",
    "GET /api/threads/{thread_id}/runs",
    "GET /api/threads/{thread_id}/runs/page",
    "GET /api/threads/{thread_id}/runs/{run_id}",
    "GET /api/threads/{thread_id}/runs/{run_id}/artifacts/archive",
    "GET /api/threads/{thread_id}/runs/{run_id}/feedback",
    "GET /api/threads/{thread_id}/runs/{run_id}/feedback/stats",
    "GET /api/threads/{thread_id}/runs/{run_id}/join",
    "GET /api/threads/{thread_id}/runs/{run_id}/messages",
    "GET /api/threads/{thread_id}/runs/{run_id}/stream",
    "GET /api/threads/{thread_id}/state",
    "GET /api/threads/{thread_id}/uploads/limits",
    "GET /api/threads/{thread_id}/uploads/list",
    "GET /api/v1/auth/me",
    "GET /api/v1/auth/preferences",
    "PATCH /api/threads/{thread_id}",
    "PATCH /api/v1/auth/preferences",
    "POST /api/workspaces/select",
    "POST /api/client-portal/threads",
    "POST /api/client-portal/threads/{thread_id}/chat",
    "POST /api/runs/stream",
    "POST /api/runs/wait",
    "POST /api/threads",
    "POST /api/threads/search",
    "POST /api/threads/{thread_id}/branches",
    "POST /api/threads/{thread_id}/compact",
    "POST /api/threads/{thread_id}/history",
    "POST /api/threads/{thread_id}/runs",
    "POST /api/threads/{thread_id}/runs/edit-regenerate/prepare",
    "POST /api/threads/{thread_id}/runs/regenerate/prepare",
    "POST /api/threads/{thread_id}/runs/stream",
    "POST /api/threads/{thread_id}/runs/wait",
    "POST /api/threads/{thread_id}/runs/{run_id}/artifacts/archive",
    "POST /api/threads/{thread_id}/runs/{run_id}/cancel",
    "POST /api/threads/{thread_id}/runs/{run_id}/feedback",
    "POST /api/threads/{thread_id}/runs/{run_id}/stream",
    "POST /api/threads/{thread_id}/state",
    "POST /api/threads/{thread_id}/suggestions",
    "POST /api/threads/{thread_id}/uploads",
    "POST /api/v1/auth/change-password",
    "POST /api/v1/auth/mfa/disable",
    "POST /api/v1/auth/mfa/enroll/confirm",
    "POST /api/v1/auth/mfa/enroll/start",
    "PUT /api/threads/{thread_id}/goal",
    "PUT /api/threads/{thread_id}/runs/{run_id}/feedback",
]

# One representative call per internal surface, including every class Dillon
# listed: team, board, academy, fleet, approvals, projects, clients, scheduled
# tasks, agents management, workflows, capability center, command center and
# the OpenAI crew.
INTERNAL_CALLS = [
    ("GET", "/api/team/channels"),
    ("POST", "/api/team/channels"),
    ("GET", "/api/academy"),
    ("POST", "/api/academy/lessons/x/progress"),
    ("GET", "/api/board/threads"),
    ("POST", "/api/board/threads/x/approve"),
    ("POST", "/api/client-portal/customer-workspaces"),
    ("POST", "/api/client-portal/customer-workspaces/invitations"),
    ("POST", "/api/client-portal/threads/x/draft"),
    ("POST", "/api/client-portal/threads/x/publish"),
    ("POST", "/api/client-portal/threads/x/work"),
    ("GET", "/api/approvals"),
    ("POST", "/api/approvals/propose"),
    ("POST", "/api/approvals/x/approve"),
    ("GET", "/api/fleet/templates"),
    ("POST", "/api/fleet/work/claim"),
    ("GET", "/api/projects"),
    ("POST", "/api/projects"),
    ("DELETE", "/api/projects/x"),
    ("GET", "/api/clients"),
    ("POST", "/api/clients"),
    ("POST", "/api/clients/import"),
    ("GET", "/api/scheduled-tasks"),
    ("POST", "/api/scheduled-tasks"),
    ("GET", "/api/threads/x/scheduled-tasks"),
    ("POST", "/api/agents"),
    ("PUT", "/api/agents/momobot-max"),
    ("DELETE", "/api/agents/momobot-max"),
    ("GET", "/api/agents/check"),
    ("PUT", "/api/agents/acme-dental-max"),
    ("DELETE", "/api/agents/acme-dental-max"),
    ("GET", "/api/user-profile"),
    ("GET", "/api/workflows/runs"),
    ("POST", "/api/workflows/runs"),
    ("GET", "/api/capabilities/catalog"),
    ("POST", "/api/capabilities/installations"),
    ("GET", "/api/command-center/board"),
    ("GET", "/api/console/stats"),
    ("GET", "/api/cost-router/spend"),
    ("GET", "/api/openai-agents/status"),
    ("POST", "/api/openai-agents/sessions"),
    ("GET", "/api/browserbase/status"),
    ("POST", "/api/threads/x/browser/navigate"),
    ("GET", "/api/mcp/config"),
    ("PUT", "/api/mcp/config"),
    ("GET", "/api/skills"),
    ("POST", "/api/skills/install"),
    ("GET", "/api/channels"),
    ("GET", "/api/channels/connections"),
    ("GET", "/api/integrations/lark/status"),
    ("GET", "/api/subagents"),
    ("GET", "/api/managed-models"),
    ("GET", "/api/memory"),
    ("GET", "/api/plugins"),
    ("GET", "/api/trash/documents"),
    ("GET", "/api/agent-room/messages"),
    ("GET", "/api/workspaces/x/branding"),
    ("GET", "/api/admin/audit-events"),
    ("PUT", "/api/admin/users/x/role"),
    ("POST", "/api/v1/auth/pats"),
    ("GET", "/api/v1/auth/pats"),
    ("POST", "/api/v1/auth/invitations"),
    ("POST", "/api/threads/x/move"),
    ("POST", "/api/threads/x/mcp-tasks"),
    ("GET", "/api/threads/x/subagent-batches"),
    ("GET", "/api/threads/x/runs/y/events"),
    ("GET", "/api/threads/x/runs/y/workspace-changes"),
    ("GET", "/api/threads/x/token-usage"),
    ("PUT", "/api/threads/x/artifacts/mnt/user-data/outputs/a.md"),
    ("POST", "/api/input-polish"),
    ("GET", "/api/assistants/x"),
    ("GET", "/api/knowledge/retrieval-catalog/datasets"),
]


@pytest.mark.parametrize("entry", CLIENT_REACHABLE_ROUTES)
def test_the_chat_routes_a_client_needs_are_allowed(entry):
    method, template = entry.split(" ", 1)
    assert is_client_allowed_route(method, _concrete(template))


def test_the_agents_api_admits_reading_one_agent_but_never_the_name_probe_or_management():
    # Which names answer is the router's call (MomoBot Max plus the client's own workspace agents, momobot_max.py).
    assert is_client_allowed_route("GET", "/api/agents/momobot-max")
    assert is_client_allowed_route("GET", "/api/agents/acme-dental-max")
    assert not is_client_allowed_route("GET", "/api/agents/check")
    assert not is_client_allowed_route("GET", "/api/agents/acme-dental-max/soul")
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        assert not is_client_allowed_route(method, "/api/agents/acme-dental-max")


@pytest.mark.parametrize(("method", "path"), INTERNAL_CALLS)
def test_every_internal_route_class_is_closed_to_a_client(method, path):
    assert not is_client_allowed_route(method, path)


def test_a_client_can_reach_exactly_the_reviewed_registered_routes():
    reachable = [f"{method} {route.path}" for route, method in _registered_calls() if is_client_allowed_route(method, _concrete(route.path))]
    assert sorted(reachable) == sorted(CLIENT_REACHABLE_ROUTES)


def test_no_rule_is_dead_so_the_table_cannot_rot_unnoticed():
    calls = [(method, _concrete(route.path)) for route, method in _registered_calls()]
    calls.append(("GET", "/api/agents/momobot-max"))
    for methods, pattern in _RULES:
        assert any(method in methods and pattern.match(path) for method, path in calls), pattern.pattern


def test_a_trailing_slash_and_the_method_case_do_not_change_the_answer():
    assert is_client_allowed_route("get", "/api/features/")
    assert not is_client_allowed_route("get", "/api/team/")


def _registered_calls():
    from app.gateway.app import create_app

    for route in create_app().routes:
        if isinstance(route, APIRoute):
            for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
                yield route, method


def _concrete(template: str) -> str:
    path = re.sub(r"\{[^}:]+:path\}", "x/y", template)
    return re.sub(r"\{[^}]+\}", "x", path)


# -- enforced by the middleware ----------------------------------------------


@pytest.fixture
def authenticated(monkeypatch):
    """Run AuthMiddleware as a signed-in user whose role the test picks."""
    role = {"value": "client"}

    async def current_user(request):
        return SimpleNamespace(id="u-1", email="u@example.test", system_role=role["value"], needs_setup=False, oauth_provider=None, oauth_id=None)

    async def active_organization(user_id, _selected=None):
        from deerflow.persistence.organizations.resolution import ActiveOrganization

        return ActiveOrganization(id=private_organization_id(user_id), name="Private organization", role="owner", storage_user_id=None)

    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "")
    monkeypatch.setattr("app.gateway.deps.get_current_user_from_request", current_user)
    monkeypatch.setattr("app.gateway.auth_middleware._resolve_active_workspace", active_organization)
    # Authorization off: the boundary must hold without any role policy.
    monkeypatch.setattr("app.gateway.authz._get_route_authorization_config", lambda: AuthorizationConfig())

    app = FastAPI()
    app.add_middleware(AuthMiddleware)

    @app.get("/api/features")
    async def features():
        return {"ok": True}

    @app.get("/api/scheduled-tasks")
    async def scheduled_tasks():
        return {"tasks": ["internal"]}

    @app.post("/api/threads/{thread_id}/runs/stream")
    async def stream(thread_id: str):
        return {"ok": True}

    @app.get("/api/team/channels")
    async def team():
        return {"channels": ["internal"]}

    client = TestClient(app, cookies={"access_token": "session"})
    return client, role


def test_the_middleware_answers_403_to_a_client_on_an_internal_route(authenticated):
    client, _ = authenticated
    for path in ("/api/scheduled-tasks", "/api/team/channels"):
        response = client.get(path)
        assert response.status_code == 403
        assert response.json() == {"detail": "This area is not available for your account"}


def test_the_middleware_lets_a_client_through_to_chat(authenticated):
    client, _ = authenticated
    assert client.get("/api/features").status_code == 200
    assert client.post("/api/threads/t-1/runs/stream").status_code == 200


@pytest.mark.parametrize("role", ["admin", "exec", "user"])
def test_other_roles_are_not_confined(authenticated, role):
    client, current_role = authenticated
    current_role["value"] = role
    assert client.get("/api/scheduled-tasks").status_code == 200
    assert client.get("/api/team/channels").status_code == 200
