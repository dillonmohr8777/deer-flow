"""Admin user controls (disable/enable/force-logout) and the audit-events list.

Router functions are called directly (the same lightweight pattern
``test_mcp_config_secrets.py`` uses for other require_admin_user routes),
with a fake request carrying ``state.user`` / ``state.auth_source`` and a
real in-memory ``AuditEventRepository`` on ``app.state`` so audited actions
can be verified end to end, not just at the repository layer.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.gateway.auth.models import User
from app.gateway.auth_disabled import AUTH_SOURCE_SESSION
from app.gateway.routers import admin as admin_router
from deerflow.persistence.audit_events import AuditEventRepository, AuditEventRow
from deerflow.persistence.base import Base

pytestmark = pytest.mark.asyncio


class _FakeProvider:
    """Stands in for get_local_provider(): an in-memory User store."""

    def __init__(self, users: dict[str, User]) -> None:
        self._users = users

    async def get_user(self, user_id: str) -> User | None:
        return self._users.get(user_id)

    async def update_user(self, user: User) -> User:
        self._users[str(user.id)] = user
        return user


@pytest_asyncio.fixture()
async def audit_repo():
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=[AuditEventRow.__table__]))
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    yield AuditEventRepository(session_factory)
    await engine.dispose()


def _request(*, system_role: str, actor_id: str = "admin-1", audit_repo=None):
    return SimpleNamespace(
        state=SimpleNamespace(user=SimpleNamespace(id=actor_id, system_role=system_role), auth_source=AUTH_SOURCE_SESSION),
        app=SimpleNamespace(state=SimpleNamespace(audit_repo=audit_repo)),
        client=None,
        headers={},
    )


def _target_user(user_id: str) -> User:
    # The fake provider's dict is keyed by the path-parameter string; the
    # pydantic User.id field is a real UUID unrelated to that key.
    return User(id=uuid4(), email=f"{user_id}@example.com", password_hash="hash", system_role="user")


@pytest.fixture(autouse=True)
def _patch_provider(monkeypatch):
    users: dict[str, User] = {}
    provider = _FakeProvider(users)
    monkeypatch.setattr(admin_router, "get_local_provider", lambda: provider)
    return users


# ── deny-by-default ─────────────────────────────────────────────────────


async def test_disable_user_requires_admin():
    with pytest.raises(HTTPException) as exc_info:
        await admin_router.disable_user("target-1", _request(system_role="user"))
    assert exc_info.value.status_code == 403


async def test_enable_user_requires_admin():
    with pytest.raises(HTTPException) as exc_info:
        await admin_router.enable_user("target-1", _request(system_role="user"))
    assert exc_info.value.status_code == 403


async def test_force_logout_requires_admin():
    with pytest.raises(HTTPException) as exc_info:
        await admin_router.force_logout_user("target-1", _request(system_role="user"))
    assert exc_info.value.status_code == 403


async def test_list_audit_events_requires_admin():
    with pytest.raises(HTTPException) as exc_info:
        await admin_router.list_audit_events(_request(system_role="user"))
    assert exc_info.value.status_code == 403


async def test_disable_user_not_found(_patch_provider):
    with pytest.raises(HTTPException) as exc_info:
        await admin_router.disable_user("missing", _request(system_role="admin"))
    assert exc_info.value.status_code == 404


# ── behavior + audit rows ────────────────────────────────────────────────


async def test_disable_user_sets_disabled_at_and_records_audit(_patch_provider, audit_repo):
    _patch_provider["target-1"] = _target_user("target-1")
    response = await admin_router.disable_user("target-1", _request(system_role="admin", audit_repo=audit_repo))

    assert response.disabled_at is not None
    assert _patch_provider["target-1"].disabled_at is not None

    events, _ = await audit_repo.list(organization_id=None)
    assert len(events) == 1
    assert events[0]["action"] == "admin.user.disabled"
    assert events[0]["outcome"] == "success"
    assert events[0]["actor_user_id"] == "admin-1"
    assert events[0]["target_id"] == "target-1"


async def test_enable_user_clears_disabled_at_and_records_audit(_patch_provider, audit_repo):
    target = _target_user("target-1")
    target.disabled_at = datetime.now(UTC)
    _patch_provider["target-1"] = target

    response = await admin_router.enable_user("target-1", _request(system_role="admin", audit_repo=audit_repo))

    assert response.disabled_at is None
    assert _patch_provider["target-1"].disabled_at is None
    events, _ = await audit_repo.list(organization_id=None, action_prefix="admin.user.enabled")
    assert len(events) == 1


async def test_force_logout_bumps_token_version_and_records_audit(_patch_provider, audit_repo):
    target = _target_user("target-1")
    target.token_version = 3
    _patch_provider["target-1"] = target

    response = await admin_router.force_logout_user("target-1", _request(system_role="admin", audit_repo=audit_repo))

    assert response.token_version == 4
    assert _patch_provider["target-1"].token_version == 4
    events, _ = await audit_repo.list(organization_id=None, action_prefix="admin.user.force_logout")
    assert len(events) == 1


# ── audit-events listing ─────────────────────────────────────────────────


def _list_events(request, **overrides):
    """Call list_audit_events with every Query() param resolved explicitly.

    Calling a FastAPI-decorated endpoint directly (matching the pattern this
    codebase already uses for other require_admin_user routes, e.g.
    test_mcp_config_secrets.py) bypasses dependency injection, so any
    parameter not passed by the caller keeps its raw fastapi.Query(...)
    sentinel object instead of resolving to that Query's ``default=``. Every
    call site must therefore pass all of them explicitly.
    """
    params = {"action_prefix": None, "actor": None, "since": None, "until": None, "cursor": None, "limit": 50}
    params.update(overrides)
    return admin_router.list_audit_events(request, **params)


async def test_list_audit_events_applies_filters(audit_repo):
    await audit_repo.record(action="auth.login.succeeded", outcome="success", actor_user_id="u1")
    await audit_repo.record(action="auth.login.failed", outcome="denied", actor_user_id=None)
    await audit_repo.record(action="admin.user.disabled", outcome="success", actor_user_id="admin-1")

    response = await _list_events(_request(system_role="admin", audit_repo=audit_repo), action_prefix="auth.login.")

    assert len(response.events) == 2
    assert {event.action for event in response.events} == {"auth.login.succeeded", "auth.login.failed"}


async def test_list_audit_events_paginates(audit_repo):
    for i in range(3):
        await audit_repo.record(action=f"a.event{i}", outcome="success")

    first_page = await _list_events(_request(system_role="admin", audit_repo=audit_repo), limit=2)
    assert len(first_page.events) == 2
    assert first_page.next_cursor is not None

    second_page = await _list_events(_request(system_role="admin", audit_repo=audit_repo), limit=2, cursor=first_page.next_cursor)
    assert len(second_page.events) == 1
    assert second_page.next_cursor is None
