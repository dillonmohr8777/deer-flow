"""A disabled user cannot log in, and any existing session stops validating.

Two independent guards, both added alongside the audit log / admin controls:
  1. LocalAuthProvider.authenticate() refuses a disabled account (login).
  2. get_current_user_from_request() 401s a disabled account's still-valid
     JWT (existing sessions).
"""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import quote
from uuid import uuid4

import pytest
from starlette.requests import Request

from app.gateway import deps
from app.gateway.auth.config import AuthConfig
from app.gateway.auth.jwt import create_access_token
from app.gateway.auth.local_provider import LocalAuthProvider
from app.gateway.auth.models import User
from app.gateway.auth.password import hash_password_async
from app.gateway.auth.session_cookie import ACCESS_TOKEN_COOKIE_NAME

pytestmark = pytest.mark.asyncio


class _FakeUserRepository:
    def __init__(self, user: User) -> None:
        self._user = user

    async def get_user_by_email(self, email: str) -> User | None:
        return self._user if self._user.email == email else None

    async def get_user_by_id(self, user_id: str) -> User | None:
        return self._user if str(self._user.id) == user_id else None

    async def update_user(self, user: User) -> User:
        self._user = user
        return user


def _cookie_request(token: str) -> Request:
    headers = [(b"cookie", f"{quote(ACCESS_TOKEN_COOKIE_NAME)}={quote(token)}".encode())]
    return Request({"type": "http", "method": "GET", "path": "/api/v1/auth/me", "headers": headers, "scheme": "http", "server": ("testserver", 80), "client": ("testclient", 1234), "query_string": b""})


async def test_local_authenticate_rejects_disabled_user_with_correct_password():
    password_hash = await hash_password_async("correct horse battery staple")
    user = User(email="disabled@example.com", password_hash=password_hash, system_role="user", disabled_at=datetime.now(UTC))
    provider = LocalAuthProvider(repository=_FakeUserRepository(user))

    result = await provider.authenticate({"email": "disabled@example.com", "password": "correct horse battery staple"})

    assert result is None


async def test_local_authenticate_allows_enabled_user_with_correct_password():
    password_hash = await hash_password_async("correct horse battery staple")
    user = User(email="active@example.com", password_hash=password_hash, system_role="user", disabled_at=None)
    provider = LocalAuthProvider(repository=_FakeUserRepository(user))

    result = await provider.authenticate({"email": "active@example.com", "password": "correct horse battery staple"})

    assert result is not None
    assert result.disabled_at is None


async def test_get_current_user_from_request_rejects_disabled_user_valid_token(monkeypatch):
    monkeypatch.setattr("app.gateway.auth.config._auth_config", AuthConfig(jwt_secret="disabled-user-test-secret"))
    user_id = str(uuid4())
    disabled_user = User(id=user_id, email="disabled@example.com", password_hash="hash", system_role="user", token_version=0, disabled_at=datetime.now(UTC))

    class _Provider:
        async def get_user(self, requested_id: str) -> User | None:
            return disabled_user if requested_id == user_id else None

    monkeypatch.setattr(deps, "get_local_provider", lambda: _Provider())

    token = create_access_token(user_id, token_version=0)
    request = _cookie_request(token)

    with pytest.raises(Exception) as exc_info:
        await deps.get_current_user_from_request(request)

    assert getattr(exc_info.value, "status_code", None) == 401


async def test_get_current_user_from_request_allows_enabled_user_valid_token(monkeypatch):
    monkeypatch.setattr("app.gateway.auth.config._auth_config", AuthConfig(jwt_secret="disabled-user-test-secret"))
    user_id = str(uuid4())
    active_user = User(id=user_id, email="active@example.com", password_hash="hash", system_role="user", token_version=0, disabled_at=None)

    class _Provider:
        async def get_user(self, requested_id: str) -> User | None:
            return active_user if requested_id == user_id else None

    monkeypatch.setattr(deps, "get_local_provider", lambda: _Provider())

    token = create_access_token(user_id, token_version=0)
    request = _cookie_request(token)

    result = await deps.get_current_user_from_request(request)

    assert str(result.id) == user_id
