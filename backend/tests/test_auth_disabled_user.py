"""A disabled user cannot log in, and nothing they hold keeps working.

Independent guards, added alongside the audit log / admin controls:
  1. LocalAuthProvider.authenticate() refuses a disabled account (login).
  2. get_current_user_from_request() 401s a disabled account's still-valid
     JWT (existing sessions).
  3. authenticate_pat() 401s a disabled owner's personal access token.
  4. active_organization_for_user() gives a disabled account no organization,
     so its internal delegations (scheduled tasks, channels) stop resolving.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from urllib.parse import quote
from uuid import uuid4

import pytest
from fastapi import HTTPException
from org_isolation_fixtures import ORG_A, USER_A, USER_B, org_world  # noqa: F401
from sqlalchemy import update
from starlette.requests import Request

from app.gateway import deps
from app.gateway.auth.config import AuthConfig
from app.gateway.auth.jwt import create_access_token
from app.gateway.auth.local_provider import LocalAuthProvider
from app.gateway.auth.models import User
from app.gateway.auth.password import hash_password_async
from app.gateway.auth.pat import authenticate_pat, generate_pat_token, pat_token_digest
from app.gateway.auth.session_cookie import ACCESS_TOKEN_COOKIE_NAME
from deerflow.persistence.organizations.delegation import OrganizationDelegationRepository
from deerflow.persistence.organizations.resolution import active_organization_for_user
from deerflow.persistence.user.model import UserRow

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


async def test_authenticate_pat_rejects_disabled_owner(monkeypatch):
    token = generate_pat_token()
    user_id = str(uuid4())
    owner = User(id=user_id, email="owner@example.com", password_hash="hash", system_role="user", disabled_at=None)

    class _PatRepo:
        async def get_active_by_digest(self, digest: str):
            return {"id": "pat-1", "user_id": user_id, "token_digest": pat_token_digest(token), "scopes": ["threads:read"]} if digest == pat_token_digest(token) else None

        async def touch_last_used(self, pat_id: str) -> None:
            pass

    class _Provider:
        async def get_user(self, requested_id: str) -> User | None:
            return owner if requested_id == user_id else None

    monkeypatch.setattr(deps, "get_local_provider", lambda: _Provider())
    app = SimpleNamespace(state=SimpleNamespace(pat_repo=_PatRepo()))

    user, scopes, organization_id = await authenticate_pat(app, f"Bearer {token}")
    assert str(user.id) == user_id and scopes == frozenset({"threads:read"}) and organization_id is None

    owner.disabled_at = datetime.now(UTC)
    with pytest.raises(HTTPException) as exc_info:
        await authenticate_pat(app, f"Bearer {token}")
    assert (exc_info.value.status_code, exc_info.value.detail) == (401, "Invalid token")


async def test_disabled_account_keeps_no_organization_or_delegation(org_world):  # noqa: F811
    delegations = OrganizationDelegationRepository(org_world)
    granted = await delegations.grant(organization_id=ORG_A, subject_type="scheduled_task", subject_id="task-a", owner_user_id=USER_A, scopes=["runs:create"])
    assert await delegations.resolve_delegation_by_id(granted) is not None

    async with org_world() as session, session.begin():
        await session.execute(update(UserRow).where(UserRow.id == USER_A).values(disabled_at=datetime.now(UTC)))

    assert await delegations.resolve_delegation_by_id(granted) is None
    async with org_world() as session:
        assert await active_organization_for_user(session, USER_A) is None
        assert await active_organization_for_user(session, USER_B) is not None
