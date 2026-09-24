"""Tests for the global AuthMiddleware (fail-closed safety net)."""

import pytest
from starlette.testclient import TestClient

from app.gateway.auth_middleware import AuthMiddleware, _is_public
from app.gateway.csrf_middleware import CSRFMiddleware
from deerflow.config.authorization_config import AuthorizationConfig
from deerflow.persistence.organizations.identity import private_organization_id


@pytest.fixture(autouse=True)
def _default_route_authorization_config(monkeypatch):
    """Keep minimal middleware apps independent of a repository config.yaml."""
    from deerflow.persistence.organizations.resolution import ActiveOrganization

    async def active_organization(request_user_id: str, _selected: str | None = None) -> ActiveOrganization:
        return ActiveOrganization(
            id=private_organization_id(request_user_id),
            name="Private organization",
            role="owner",
            storage_user_id=None,
        )

    monkeypatch.setattr(
        "app.gateway.authz._get_route_authorization_config",
        lambda: AuthorizationConfig(),
    )
    monkeypatch.setattr("app.gateway.auth_middleware._resolve_active_workspace", active_organization)


# ── _is_public unit tests ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path",
    [
        "/health",
        "/health/",
        "/docs",
        "/docs/",
        "/redoc",
        "/openapi.json",
        "/api/v1/auth/login/local",
        "/api/v1/auth/register",
        "/api/v1/auth/logout",
        "/api/v1/auth/setup-status",
    ],
)
def test_public_paths(path: str):
    assert _is_public(path) is True


@pytest.mark.parametrize(
    "path",
    [
        "/api/models",
        "/api/mcp/config",
        "/api/mcp/cache/reset",
        "/api/memory",
        "/api/skills",
        "/api/threads/123",
        "/api/threads/123/uploads",
        "/api/agents",
        "/api/channels",
        "/api/channels/providers",
        "/api/channels/slack/connect",
        "/api/runs/stream",
        "/api/threads/123/runs",
        "/api/v1/auth/me",
        "/api/v1/auth/change-password",
    ],
)
def test_protected_paths(path: str):
    assert _is_public(path) is False


# ── Trailing slash / normalization edge cases ─────────────────────────────


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/auth/login/local/",
        "/api/v1/auth/register/",
        "/api/v1/auth/logout/",
        "/api/v1/auth/setup-status/",
    ],
)
def test_public_auth_paths_with_trailing_slash(path: str):
    assert _is_public(path) is True


@pytest.mark.parametrize(
    "path",
    [
        "/api/models/",
        "/api/v1/auth/me/",
        "/api/v1/auth/change-password/",
    ],
)
def test_protected_paths_with_trailing_slash(path: str):
    assert _is_public(path) is False


def test_unknown_api_path_is_protected():
    """Fail-closed: any new /api/* path is protected by default."""
    assert _is_public("/api/new-feature") is False
    assert _is_public("/api/v2/something") is False
    assert _is_public("/api/v1/auth/new-endpoint") is False


# ── Middleware integration tests ──────────────────────────────────────────


def _make_app():
    """Create a minimal FastAPI app with AuthMiddleware for testing."""
    from fastapi import FastAPI, Request

    from deerflow.runtime.user_context import get_effective_user_id

    app = FastAPI()
    app.add_middleware(AuthMiddleware)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/v1/auth/me")
    async def auth_me(request: Request):
        from app.gateway.deps import get_current_user_from_request

        user = await get_current_user_from_request(request)
        return {
            "id": str(user.id),
            "email": user.email,
            "system_role": user.system_role,
            "needs_setup": user.needs_setup,
        }

    @app.get("/api/v1/auth/setup-status")
    async def setup_status():
        return {"needs_setup": False}

    @app.get("/api/models")
    async def models_get():
        return {"models": []}

    @app.get("/api/whoami")
    async def whoami(request: Request):
        user = request.state.user
        return {
            "id": str(user.id),
            "email": getattr(user, "email", None),
            "system_role": getattr(user, "system_role", None),
            "context_user_id": get_effective_user_id(),
        }

    @app.get("/api/current-user-from-dep")
    async def current_user_from_dep(request: Request):
        from app.gateway.deps import get_current_user_from_request

        user = await get_current_user_from_request(request)
        state_user = request.state.user
        return {
            "id": str(user.id),
            "state_id": str(state_user.id),
            "auth_source": request.state.auth_source,
            "context_user_id": get_effective_user_id(),
        }

    @app.get("/api/tenant-context")
    async def tenant_context(request: Request):
        return {
            "organization_id": getattr(request.state, "organization_id", None),
            "auth_organization_id": getattr(request.state.auth, "organization_id", None),
        }

    @app.put("/api/mcp/config")
    async def mcp_put():
        return {"ok": True}

    @app.post("/api/mcp/cache/reset")
    async def mcp_cache_reset():
        return {"ok": True}

    @app.delete("/api/threads/abc")
    async def thread_delete():
        return {"ok": True}

    @app.patch("/api/threads/abc")
    async def thread_patch():
        return {"ok": True}

    @app.post("/api/threads/abc/runs/stream")
    async def stream():
        return {"ok": True}

    @app.get("/api/future-endpoint")
    async def future():
        return {"ok": True}

    return app


def _make_auth_csrf_app():
    """Create a minimal app with production middleware ordering."""
    from fastapi import FastAPI

    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.add_middleware(CSRFMiddleware)

    @app.post("/api/threads/abc/runs/stream")
    async def protected_mutation():
        return {"ok": True}

    return app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "")
    return TestClient(_make_app())


def test_public_path_no_cookie(client):
    res = client.get("/health")
    assert res.status_code == 200


def test_public_auth_path_no_cookie(client):
    """Public auth endpoints (login/register) pass without cookie."""
    res = client.get("/api/v1/auth/setup-status")
    assert res.status_code == 200


@pytest.mark.parametrize(
    "encoded_path",
    [
        "/api/v1/auth/setup-sta%0Atus",
        "/api/v1/auth/setup-sta%0Dtus",
        "/api/v1/auth/setup-sta%09tus",
        "/api/v1/auth/setup-status%23private",
        "/api/v1/auth/setup-status%3Fprivate",
    ],
)
def test_url_reconstruction_cannot_turn_a_protected_route_path_public(
    monkeypatch,
    encoded_path,
):
    from fastapi import FastAPI

    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "")
    app = FastAPI()
    app.add_middleware(AuthMiddleware)

    @app.get("/api/v1/auth/setup-sta{gap}tus")
    async def control_gap(gap: str):
        return {"gap": gap}

    @app.get("/api/v1/auth/setup-status{suffix}")
    async def delimiter_suffix(suffix: str):
        return {"suffix": suffix}

    response = TestClient(app).get(encoded_path)

    assert response.status_code == 401


def test_auth_uses_the_same_root_path_projection_as_the_router(monkeypatch):
    from fastapi import FastAPI

    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "")
    child = FastAPI()
    child.add_middleware(AuthMiddleware)

    @child.get("/health")
    async def health():
        return {"ok": True}

    parent = FastAPI()
    parent.mount("/prefix", child)

    response = TestClient(parent).get("/prefix/health")

    assert response.status_code == 200


def test_protected_auth_path_no_cookie(client):
    """/auth/me requires cookie even though it's under /api/v1/auth/."""
    res = client.get("/api/v1/auth/me")
    assert res.status_code == 401


def test_protected_path_no_cookie_returns_401(client):
    res = client.get("/api/models")
    assert res.status_code == 401
    body = res.json()
    assert body["detail"]["code"] == "not_authenticated"


def test_auth_disabled_allows_protected_path_without_cookie(monkeypatch):
    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "1")
    client = TestClient(_make_app())

    res = client.get("/api/models")

    assert res.status_code == 200
    assert res.json() == {"models": []}


def test_auth_disabled_stamps_default_admin_user_without_cookie(monkeypatch):
    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "1")
    client = TestClient(_make_app())

    res = client.get("/api/whoami")

    assert res.status_code == 200
    assert res.json() == {
        "id": "default",
        "email": "default@test.local",
        "system_role": "admin",
        "context_user_id": "default",
    }


def test_auth_disabled_auth_me_reuses_middleware_user_without_cookie(monkeypatch):
    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "1")
    client = TestClient(_make_app())

    res = client.get("/api/v1/auth/me")

    assert res.status_code == 200
    assert res.json() == {
        "id": "default",
        "email": "default@test.local",
        "system_role": "admin",
        "needs_setup": False,
    }


def test_auth_disabled_does_not_clobber_valid_session_cookie(monkeypatch):
    from types import SimpleNamespace

    async def fake_current_user(request):
        return SimpleNamespace(
            id="session-user",
            email="session@test.local",
            system_role="user",
            needs_setup=False,
        )

    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "1")
    monkeypatch.setattr("app.gateway.deps.get_current_user_from_request", fake_current_user)
    client = TestClient(_make_app())

    res = client.get("/api/whoami", cookies={"access_token": "valid-session"})

    assert res.status_code == 200
    assert res.json() == {
        "id": "session-user",
        "email": "session@test.local",
        "system_role": "user",
        "context_user_id": "session-user",
    }


def test_session_stamps_active_private_organization(monkeypatch):
    from types import SimpleNamespace

    async def fake_current_user(request):
        return SimpleNamespace(id="session-user", email="session@test.local", system_role="user")

    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "")
    monkeypatch.setattr("app.gateway.deps.get_current_user_from_request", fake_current_user)

    response = TestClient(_make_app()).get("/api/tenant-context", cookies={"access_token": "valid-session"})

    assert response.status_code == 200
    assert response.json() == {
        "organization_id": private_organization_id("session-user"),
        "auth_organization_id": private_organization_id("session-user"),
    }


def test_session_without_active_private_organization_is_rejected(monkeypatch):
    from types import SimpleNamespace

    async def fake_current_user(request):
        return SimpleNamespace(id="session-user", email="session@test.local", system_role="user")

    async def no_active_organization(user_id: str, _selected: str | None = None):
        return None

    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "")
    monkeypatch.setattr("app.gateway.deps.get_current_user_from_request", fake_current_user)
    monkeypatch.setattr("app.gateway.auth_middleware._resolve_active_workspace", no_active_organization)

    response = TestClient(_make_app()).get("/api/tenant-context", cookies={"access_token": "valid-session"})

    assert response.status_code == 403
    assert response.json() == {"detail": "Active organization membership required"}


def test_pat_stamps_active_private_organization(monkeypatch):
    from types import SimpleNamespace

    async def fake_authenticate_pat(app, authorization):
        # organization_id=None: a pre-migration/quarantined PAT falls back to
        # the owner's private organization, same as before 0037_pat_organization.
        return SimpleNamespace(id="pat-user", email="pat@test.local", system_role="user"), frozenset({"threads:read"}), None

    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "")
    monkeypatch.setattr("app.gateway.auth.pat.authenticate_pat", fake_authenticate_pat)
    monkeypatch.setattr("app.gateway.auth.pat.is_pat_allowed_route", lambda method, path, **kwargs: True)

    response = TestClient(_make_app()).get("/api/tenant-context", headers={"Authorization": "Bearer dfp_test"})

    assert response.status_code == 200
    assert response.json() == {
        "organization_id": private_organization_id("pat-user"),
        "auth_organization_id": private_organization_id("pat-user"),
    }


def test_auth_disabled_does_not_clobber_internal_auth_identity(monkeypatch):
    from app.gateway.internal_auth import create_internal_auth_headers
    from deerflow.runtime.user_context import DEFAULT_USER_ID

    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "1")
    client = TestClient(_make_app())

    res = client.get(
        "/api/current-user-from-dep",
        headers=create_internal_auth_headers(),
    )

    assert res.status_code == 200
    assert res.json() == {
        "id": DEFAULT_USER_ID,
        "state_id": DEFAULT_USER_ID,
        "auth_source": "internal",
        "context_user_id": DEFAULT_USER_ID,
    }


def test_auth_disabled_skips_csrf_for_state_changing_requests(monkeypatch):
    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "1")
    client = TestClient(_make_auth_csrf_app())

    res = client.post("/api/threads/abc/runs/stream")

    assert res.status_code == 200
    assert res.json() == {"ok": True}


def test_auth_disabled_is_ignored_in_explicit_production_env(monkeypatch):
    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "1")
    monkeypatch.setenv("DEER_FLOW_ENV", "production")
    client = TestClient(_make_app())

    res = client.get("/api/models")

    assert res.status_code == 401


def test_auth_disabled_startup_warning_when_effective(monkeypatch, caplog):
    from app.gateway.auth_disabled import warn_if_auth_disabled_enabled

    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "1")
    monkeypatch.delenv("DEER_FLOW_ENV", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)

    with caplog.at_level("WARNING", logger="app.gateway.auth_disabled"):
        warn_if_auth_disabled_enabled()

    assert "authentication is bypassed" in caplog.text
    assert "default" in caplog.text


def test_auth_disabled_startup_warning_suppressed_in_explicit_production_env(monkeypatch, caplog):
    from app.gateway.auth_disabled import warn_if_auth_disabled_enabled

    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "1")
    monkeypatch.setenv("ENVIRONMENT", "production")

    with caplog.at_level("WARNING", logger="app.gateway.auth_disabled"):
        warn_if_auth_disabled_enabled()

    assert "authentication is bypassed" not in caplog.text


def test_protected_path_with_junk_cookie_rejected(client):
    """Junk cookie → 401. Middleware strictly validates the JWT now
    (AUTH_TEST_PLAN test 7.5.8); it no longer silently passes bad
    tokens through to the route handler."""
    client.cookies.set("access_token", "some-token")
    res = client.get("/api/models")
    assert res.status_code == 401


def test_protected_post_no_cookie_returns_401(client):
    res = client.post("/api/threads/abc/runs/stream")
    assert res.status_code == 401


def test_mcp_cache_reset_post_no_cookie_returns_401(client):
    res = client.post("/api/mcp/cache/reset")
    assert res.status_code == 401


def test_protected_post_with_internal_token_alone_is_refused():
    """Contract section 4: the internal token (plus owner header) needs a delegation."""
    from app.gateway.internal_auth import create_internal_auth_headers

    app = _make_app()
    client = TestClient(app)

    for headers in (create_internal_auth_headers(), create_internal_auth_headers(owner_user_id="owner-1")):
        res = client.post("/api/threads/abc/runs/stream", headers=headers)
        assert res.status_code == 403
        assert res.json() == {"detail": "Internal calls require an active organization delegation"}


# ── Method matrix: PUT/DELETE/PATCH also protected ────────────────────────


def test_protected_put_no_cookie(client):
    res = client.put("/api/mcp/config")
    assert res.status_code == 401


def test_protected_delete_no_cookie(client):
    res = client.delete("/api/threads/abc")
    assert res.status_code == 401


def test_protected_patch_no_cookie(client):
    res = client.patch("/api/threads/abc")
    assert res.status_code == 401


def test_put_with_junk_cookie_rejected(client):
    """Junk cookie on PUT → 401 (strict JWT validation in middleware)."""
    client.cookies.set("access_token", "tok")
    res = client.put("/api/mcp/config")
    assert res.status_code == 401


def test_delete_with_junk_cookie_rejected(client):
    """Junk cookie on DELETE → 401 (strict JWT validation in middleware)."""
    client.cookies.set("access_token", "tok")
    res = client.delete("/api/threads/abc")
    assert res.status_code == 401


# ── Fail-closed: unknown future endpoints ─────────────────────────────────


def test_unknown_endpoint_no_cookie_returns_401(client):
    """Any new /api/* endpoint is blocked by default without cookie."""
    res = client.get("/api/future-endpoint")
    assert res.status_code == 401


def test_unknown_endpoint_with_junk_cookie_rejected(client):
    """New endpoints are also protected by strict JWT validation."""
    client.cookies.set("access_token", "tok")
    res = client.get("/api/future-endpoint")
    assert res.status_code == 401
