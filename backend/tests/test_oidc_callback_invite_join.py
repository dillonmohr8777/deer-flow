"""The OAuth callback joins a brand-new SSO account to the workspace it was invited to, and opens it."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from starlette.requests import Request

from app.gateway.auth.config import AuthConfig
from app.gateway.routers import auth as auth_router


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/auth/callback/google",
            "headers": [(b"host", b"momobot.example"), (b"x-forwarded-proto", b"https")],
            "query_string": b"",
            "scheme": "https",
            "server": ("momobot.example", 443),
            "client": ("203.0.113.9", 4321),
        }
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(("created", "verified", "joins", "join_fails"), [(True, True, True, False), (False, True, False, False), (True, False, False, False), (True, True, False, True)])
async def test_the_callback_opens_the_invited_workspace_only_for_a_new_verified_account(monkeypatch, created, verified, joins, join_fails):
    endpoints = dict(authorization_endpoint=None, token_endpoint=None, userinfo_endpoint=None, jwks_uri=None)
    provider = SimpleNamespace(issuer="https://accounts.google.com", client_id="momobot", client_secret="unused", token_endpoint_auth_method="client_secret_post", **endpoints)
    app_config = SimpleNamespace(auth=SimpleNamespace(oidc=SimpleNamespace(enabled=True, frontend_base_url="https://momobot.example", providers={"google": provider})))
    monkeypatch.setattr("deerflow.config.app_config.get_app_config", lambda: app_config)
    monkeypatch.setattr("app.gateway.auth.config._auth_config", AuthConfig(jwt_secret="oidc-callback-invite-join-test-secret"))
    monkeypatch.setattr(auth_router, "get_state_cookie", lambda request, provider_id: SimpleNamespace(state="s", code_verifier="v", nonce="n", next_path=None, remember_me=False))
    monkeypatch.setattr(auth_router, "_resolve_oidc_redirect_uri", lambda *args: "https://momobot.example/api/v1/auth/callback/google")
    identity = SimpleNamespace(email="partner@example.com", email_verified=verified)
    monkeypatch.setattr(auth_router, "_get_oidc_service", lambda: SimpleNamespace(discover=AsyncMock(return_value={}), authenticate_callback=AsyncMock(return_value=identity)))
    user = SimpleNamespace(id="u-new", email="partner@example.com", token_version=0)
    monkeypatch.setattr(auth_router, "get_or_provision_oidc_user", AsyncMock(return_value={"user": user, "created": created}))
    monkeypatch.setattr(auth_router, "get_local_provider", lambda: object())
    join = AsyncMock(side_effect=RuntimeError("database hiccup") if join_fails else None, return_value="workspace-1")
    monkeypatch.setattr("app.gateway.routers.invitations.join_invited_workspaces", join)

    response = await auth_router.oauth_callback(_request(), "google", code="c", state="s")

    cookies = [value.decode() for key, value in response.raw_headers if key == b"set-cookie"]
    assert any(cookie.startswith("access_token=") for cookie in cookies)
    assert any(cookie.startswith("deerflow_workspace=workspace-1") for cookie in cookies) is joins
    assert join.await_count == (1 if created and verified else 0)  # a failed join still signs the person in
