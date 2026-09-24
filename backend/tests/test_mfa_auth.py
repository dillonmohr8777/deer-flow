"""End-to-end TOTP MFA tests: enrollment, login gating, recovery codes,
rate limiting, audit rows, and disabled-user rejection.

Mirrors the full-app TestClient pattern in tests/test_pat_auth.py (real
AuthMiddleware + CSRFMiddleware + auth_router over a real SQLite DB), but
uses the real LocalAuthProvider/SQLiteUserRepository instead of a fake so
password login and the MFA challenge branch run exactly as production.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.testclient import TestClient

import deerflow.persistence.models  # noqa: F401  (register every table)
from app.gateway.auth.local_provider import LocalAuthProvider
from app.gateway.auth.repositories.sqlite import SQLiteUserRepository
from app.gateway.auth.totp import totp_code
from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.csrf_middleware import CSRF_COOKIE_NAME, CSRF_HEADER_NAME, CSRFMiddleware, generate_csrf_token
from app.gateway.routers.auth import router as auth_router
from deerflow.config.authorization_config import AuthorizationConfig
from deerflow.persistence.audit_events import AuditEventRepository
from deerflow.persistence.base import Base
from deerflow.persistence.user_mfa import UserMfaRepository

TEST_JWT_SECRET = "test-mfa-jwt-secret-0123456789abcdef-32b"
TEST_PASSWORD = "correct horse battery staple"


@pytest.fixture(autouse=True)
def _default_route_authorization_config(monkeypatch):
    monkeypatch.setattr("app.gateway.authz._get_route_authorization_config", lambda: AuthorizationConfig())
    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "")
    from app.gateway.auth.config import AuthConfig, set_auth_config

    set_auth_config(AuthConfig(jwt_secret=TEST_JWT_SECRET, token_expiry_days=7))


@pytest.fixture(autouse=True)
def _reset_mfa_challenge_state():
    """The challenge-attempt dict is process-global; isolate tests from each other."""
    from app.gateway.routers import auth as auth_module

    auth_module._mfa_challenges.clear()
    auth_module._login_attempts.clear()
    yield
    auth_module._mfa_challenges.clear()
    auth_module._login_attempts.clear()


async def _create_tables(engine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _make_app() -> FastAPI:
    app = FastAPI()
    # Production order: AuthMiddleware added first (inner), CSRF last (outer).
    app.add_middleware(AuthMiddleware)
    app.add_middleware(CSRFMiddleware)
    app.include_router(auth_router)
    return app


@pytest.fixture
def mfa_env(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/mfa.db", poolclass=NullPool)
    asyncio.run(_create_tables(engine))
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("deerflow.persistence.engine.get_session_factory", lambda: session_factory)

    local_provider = LocalAuthProvider(repository=SQLiteUserRepository(session_factory))
    monkeypatch.setattr("app.gateway.deps.get_local_provider", lambda: local_provider)
    monkeypatch.setattr("app.gateway.routers.auth.get_local_provider", lambda: local_provider)

    mfa_repo = UserMfaRepository(session_factory)
    audit_repo = AuditEventRepository(session_factory)

    app = _make_app()
    app.state.mfa_repo = mfa_repo
    app.state.audit_repo = audit_repo

    user = asyncio.run(local_provider.create_user(email="alice@example.com", password=TEST_PASSWORD, system_role="user"))
    disabled_user = asyncio.run(local_provider.create_user(email="bob@example.com", password=TEST_PASSWORD, system_role="user"))

    return SimpleNamespace(
        app=app,
        engine=engine,
        session_factory=session_factory,
        local_provider=local_provider,
        mfa_repo=mfa_repo,
        audit_repo=audit_repo,
        user=user,
        disabled_user=disabled_user,
    )


@pytest.fixture
def client(mfa_env):
    with TestClient(mfa_env.app) as test_client:
        yield test_client
    asyncio.run(mfa_env.engine.dispose())


def _session_cookie(client: TestClient, user_id: str, token_version: int = 0) -> None:
    from app.gateway.auth import create_access_token

    client.cookies.set("access_token", create_access_token(user_id, token_version=token_version))


def _csrf_headers(client: TestClient) -> dict[str, str]:
    csrf = generate_csrf_token()
    client.cookies.set(CSRF_COOKIE_NAME, csrf)
    return {CSRF_HEADER_NAME: csrf}


def _login_local(client: TestClient, email: str, password: str):
    return client.post("/api/v1/auth/login/local", data={"username": email, "password": password})


def _enroll(client: TestClient, user_id: str) -> dict:
    """Full enroll start + confirm; returns {"secret": ..., "recovery_codes": [...]}."""
    _session_cookie(client, user_id)
    start = client.post("/api/v1/auth/mfa/enroll/start", headers=_csrf_headers(client))
    assert start.status_code == 200, start.text
    secret = start.json()["secret"]

    _session_cookie(client, user_id)
    confirm = client.post("/api/v1/auth/mfa/enroll/confirm", json={"code": totp_code(secret)}, headers=_csrf_headers(client))
    assert confirm.status_code == 200, confirm.text
    return {"secret": secret, "recovery_codes": confirm.json()["recovery_codes"]}


# ── Enrollment ─────────────────────────────────────────────────────────────


def test_enroll_start_returns_secret_and_otpauth_uri(client, mfa_env):
    _session_cookie(client, str(mfa_env.user.id))
    response = client.post("/api/v1/auth/mfa/enroll/start", headers=_csrf_headers(client))
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["secret"]) >= 16
    assert body["otpauth_uri"].startswith("otpauth://totp/")
    assert body["secret"] in body["otpauth_uri"]


def test_enroll_confirm_with_wrong_code_is_rejected_and_does_not_enable(client, mfa_env):
    _session_cookie(client, str(mfa_env.user.id))
    client.post("/api/v1/auth/mfa/enroll/start", headers=_csrf_headers(client))

    _session_cookie(client, str(mfa_env.user.id))
    response = client.post("/api/v1/auth/mfa/enroll/confirm", json={"code": "000000"}, headers=_csrf_headers(client))
    assert response.status_code == 401

    me = client.get("/api/v1/auth/me")
    assert me.json()["mfa_enabled"] is False


def test_enroll_confirm_returns_ten_recovery_codes_and_enables(client, mfa_env):
    result = _enroll(client, str(mfa_env.user.id))
    assert len(result["recovery_codes"]) == 10
    assert len(set(result["recovery_codes"])) == 10

    me = client.get("/api/v1/auth/me")
    assert me.json()["mfa_enabled"] is True


def test_enroll_start_conflicts_once_already_enabled(client, mfa_env):
    _enroll(client, str(mfa_env.user.id))
    _session_cookie(client, str(mfa_env.user.id))
    response = client.post("/api/v1/auth/mfa/enroll/start", headers=_csrf_headers(client))
    assert response.status_code == 409


def test_enroll_confirm_records_mfa_enabled_audit_row(client, mfa_env):
    _enroll(client, str(mfa_env.user.id))
    rows, _ = asyncio.run(mfa_env.audit_repo.list(organization_id=None, action_prefix="mfa.enabled"))
    assert len(rows) == 1
    assert rows[0]["actor_user_id"] == str(mfa_env.user.id)
    assert rows[0]["outcome"] == "success"


# ── Login gating ─────────────────────────────────────────────────────────


def test_login_without_mfa_returns_a_normal_session(client, mfa_env):
    response = _login_local(client, mfa_env.user.email, TEST_PASSWORD)
    assert response.status_code == 200
    body = response.json()
    assert body["mfa_required"] is False
    assert "access_token" in client.cookies


def test_login_with_mfa_enabled_returns_a_challenge_not_a_session(client, mfa_env):
    _enroll(client, str(mfa_env.user.id))
    client.cookies.clear()

    response = _login_local(client, mfa_env.user.email, TEST_PASSWORD)
    assert response.status_code == 200
    body = response.json()
    assert body["mfa_required"] is True
    assert isinstance(body["challenge"], str) and body["challenge"]
    assert "access_token" not in client.cookies


def test_login_mfa_with_valid_code_completes_the_session(client, mfa_env):
    enrolled = _enroll(client, str(mfa_env.user.id))
    client.cookies.clear()

    challenge = _login_local(client, mfa_env.user.email, TEST_PASSWORD).json()["challenge"]
    response = client.post("/api/v1/auth/login/mfa", json={"challenge": challenge, "code": totp_code(enrolled["secret"])})
    assert response.status_code == 200, response.text
    assert response.json()["mfa_required"] is False
    assert "access_token" in client.cookies


def test_login_mfa_with_wrong_code_is_rejected(client, mfa_env):
    _enroll(client, str(mfa_env.user.id))
    client.cookies.clear()

    challenge = _login_local(client, mfa_env.user.email, TEST_PASSWORD).json()["challenge"]
    response = client.post("/api/v1/auth/login/mfa", json={"challenge": challenge, "code": "000000"})
    assert response.status_code == 401
    detail = response.json()["detail"]
    assert detail["code"] == "invalid_credentials"


def test_login_mfa_challenge_is_single_use(client, mfa_env):
    enrolled = _enroll(client, str(mfa_env.user.id))
    client.cookies.clear()

    challenge = _login_local(client, mfa_env.user.email, TEST_PASSWORD).json()["challenge"]
    code = totp_code(enrolled["secret"])
    first = client.post("/api/v1/auth/login/mfa", json={"challenge": challenge, "code": code})
    assert first.status_code == 200

    second = client.post("/api/v1/auth/login/mfa", json={"challenge": challenge, "code": code})
    assert second.status_code == 401


def test_login_mfa_recovery_code_is_single_use(client, mfa_env):
    enrolled = _enroll(client, str(mfa_env.user.id))
    recovery_code = enrolled["recovery_codes"][0]
    client.cookies.clear()

    challenge = _login_local(client, mfa_env.user.email, TEST_PASSWORD).json()["challenge"]
    first = client.post("/api/v1/auth/login/mfa", json={"challenge": challenge, "recovery_code": recovery_code})
    assert first.status_code == 200, first.text

    client.cookies.clear()
    challenge2 = _login_local(client, mfa_env.user.email, TEST_PASSWORD).json()["challenge"]
    second = client.post("/api/v1/auth/login/mfa", json={"challenge": challenge2, "recovery_code": recovery_code})
    assert second.status_code == 401


def test_login_mfa_recovery_code_use_records_audit_row(client, mfa_env):
    enrolled = _enroll(client, str(mfa_env.user.id))
    client.cookies.clear()
    challenge = _login_local(client, mfa_env.user.email, TEST_PASSWORD).json()["challenge"]
    client.post("/api/v1/auth/login/mfa", json={"challenge": challenge, "recovery_code": enrolled["recovery_codes"][0]})

    rows, _ = asyncio.run(mfa_env.audit_repo.list(organization_id=None, action_prefix="mfa.recovery_code.used"))
    assert len(rows) == 1
    assert rows[0]["actor_user_id"] == str(mfa_env.user.id)


def test_login_mfa_challenge_exhausts_after_five_attempts(client, mfa_env):
    from app.gateway.routers import auth as auth_module

    enrolled = _enroll(client, str(mfa_env.user.id))
    client.cookies.clear()
    challenge = _login_local(client, mfa_env.user.email, TEST_PASSWORD).json()["challenge"]

    for _ in range(5):
        response = client.post("/api/v1/auth/login/mfa", json={"challenge": challenge, "code": "000000"})
        assert response.status_code == 401

    # Isolate the challenge-exhaustion behavior from the IP lockout that the
    # same 5 failures also tripped (both are real, stacked protections; this
    # assertion is specifically about the challenge's own attempt budget).
    auth_module._login_attempts.clear()

    # The 6th attempt -- even with the *correct* code -- is rejected: the
    # challenge itself is spent, not just the wrong-code count.
    response = client.post("/api/v1/auth/login/mfa", json={"challenge": challenge, "code": totp_code(enrolled["secret"])})
    assert response.status_code == 401


def test_login_mfa_records_challenge_failed_audit_row(client, mfa_env):
    _enroll(client, str(mfa_env.user.id))
    client.cookies.clear()
    challenge = _login_local(client, mfa_env.user.email, TEST_PASSWORD).json()["challenge"]
    client.post("/api/v1/auth/login/mfa", json={"challenge": challenge, "code": "000000"})

    rows, _ = asyncio.run(mfa_env.audit_repo.list(organization_id=None, action_prefix="mfa.challenge.failed"))
    assert len(rows) == 1
    assert rows[0]["outcome"] == "denied"


def test_login_mfa_garbage_challenge_is_rejected_generically(client, mfa_env):
    response = client.post("/api/v1/auth/login/mfa", json={"challenge": "not-a-real-token", "code": "123456"})
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "invalid_credentials"


# ── Disable ────────────────────────────────────────────────────────────────


def test_disable_requires_password_and_code(client, mfa_env):
    enrolled = _enroll(client, str(mfa_env.user.id))
    _session_cookie(client, str(mfa_env.user.id))

    wrong_password = client.post("/api/v1/auth/mfa/disable", json={"password": "wrong-password", "code": totp_code(enrolled["secret"])}, headers=_csrf_headers(client))
    assert wrong_password.status_code == 401

    _session_cookie(client, str(mfa_env.user.id))
    me_still_enabled = client.get("/api/v1/auth/me")
    assert me_still_enabled.json()["mfa_enabled"] is True


def test_disable_with_valid_password_and_code_disables(client, mfa_env):
    enrolled = _enroll(client, str(mfa_env.user.id))
    _session_cookie(client, str(mfa_env.user.id))

    response = client.post("/api/v1/auth/mfa/disable", json={"password": TEST_PASSWORD, "code": totp_code(enrolled["secret"])}, headers=_csrf_headers(client))
    assert response.status_code == 200, response.text

    _session_cookie(client, str(mfa_env.user.id))
    me = client.get("/api/v1/auth/me")
    assert me.json()["mfa_enabled"] is False

    rows, _ = asyncio.run(mfa_env.audit_repo.list(organization_id=None, action_prefix="mfa.disabled"))
    assert len(rows) == 1


def test_disable_with_recovery_code_also_works(client, mfa_env):
    enrolled = _enroll(client, str(mfa_env.user.id))
    _session_cookie(client, str(mfa_env.user.id))

    response = client.post("/api/v1/auth/mfa/disable", json={"password": TEST_PASSWORD, "recovery_code": enrolled["recovery_codes"][0]}, headers=_csrf_headers(client))
    assert response.status_code == 200, response.text


def test_after_disable_login_no_longer_requires_mfa(client, mfa_env):
    enrolled = _enroll(client, str(mfa_env.user.id))
    _session_cookie(client, str(mfa_env.user.id))
    client.post("/api/v1/auth/mfa/disable", json={"password": TEST_PASSWORD, "code": totp_code(enrolled["secret"])}, headers=_csrf_headers(client))
    client.cookies.clear()

    response = _login_local(client, mfa_env.user.email, TEST_PASSWORD)
    assert response.json()["mfa_required"] is False


# ── Disabled account ─────────────────────────────────────────────────────


def test_disabled_account_cannot_complete_mfa_login(client, mfa_env):
    enrolled = _enroll(client, str(mfa_env.user.id))
    client.cookies.clear()
    challenge = _login_local(client, mfa_env.user.email, TEST_PASSWORD).json()["challenge"]

    async def _disable_account():
        from datetime import UTC, datetime

        user = await mfa_env.local_provider.get_user(str(mfa_env.user.id))
        user.disabled_at = datetime.now(UTC)
        await mfa_env.local_provider.update_user(user)

    asyncio.run(_disable_account())

    response = client.post("/api/v1/auth/login/mfa", json={"challenge": challenge, "code": totp_code(enrolled["secret"])})
    assert response.status_code == 401


def test_disabled_account_cannot_password_login_at_all(client, mfa_env):
    async def _disable_account():
        from datetime import UTC, datetime

        user = await mfa_env.local_provider.get_user(str(mfa_env.disabled_user.id))
        user.disabled_at = datetime.now(UTC)
        await mfa_env.local_provider.update_user(user)

    asyncio.run(_disable_account())

    response = _login_local(client, mfa_env.disabled_user.email, TEST_PASSWORD)
    assert response.status_code == 401


# ── PAT / non-session credentials cannot manage MFA (#4849-style rule) ────


def test_mfa_management_requires_interactive_session(client, mfa_env):
    """No Authorization/session at all -> 401, not a silent bypass.

    A valid CSRF pair is supplied so the CSRF double-submit check (which
    runs before AuthMiddleware in the real stack) does not mask this: the
    property under test is the *auth* boundary, not the CSRF one.
    """
    response = client.post("/api/v1/auth/mfa/enroll/start", headers=_csrf_headers(client))
    assert response.status_code == 401
