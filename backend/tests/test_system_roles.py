"""System roles: ``exec`` and ``client`` are real roles, neither is admin, and an unknown role never works."""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.gateway.auth.models import SystemRole, User, UserResponse
from app.gateway.auth_disabled import AUTH_SOURCE_PAT, AUTH_SOURCE_SESSION
from app.gateway.deps import is_admin_user, require_admin_user
from app.gateway.routers import admin as admin_router
from app.gateway.routers import cost_router, managed_models
from deerflow.authz.rbac import RbacAuthorizationProvider
from deerflow.config.authorization_config import AuthorizationConfig
from deerflow.persistence.audit_events import AuditEventRepository, AuditEventRow
from deerflow.persistence.base import Base

ROLES = ("admin", "exec", "user", "client")
NOT_ADMIN = ("exec", "user", "client")


def _request(*, system_role: str, actor_id: str = "admin-1", audit_repo=None, auth_source: str = AUTH_SOURCE_SESSION):
    return SimpleNamespace(
        state=SimpleNamespace(user=SimpleNamespace(id=actor_id, system_role=system_role), auth_source=auth_source),
        app=SimpleNamespace(state=SimpleNamespace(audit_repo=audit_repo, run_store=None)),
        client=None,
        headers={},
    )


# -- parsing ------------------------------------------------------------------


def test_the_four_roles_are_exactly_the_valid_system_roles():
    assert set(SystemRole.__args__) == set(ROLES)


@pytest.mark.parametrize("role", ROLES)
def test_every_role_parses_on_the_user_and_its_response(role):
    assert User(email="a@example.com", system_role=role).system_role == role
    assert UserResponse(id="1", email="a@example.com", system_role=role).system_role == role


@pytest.mark.parametrize("role", ["superuser", "Admin", "owner", "internal", ""])
def test_an_unknown_role_cannot_be_parsed_so_it_can_never_authenticate(role):
    with pytest.raises(ValidationError):
        User(email="a@example.com", system_role=role)
    with pytest.raises(ValidationError):
        UserResponse(id="1", email="a@example.com", system_role=role)


@pytest.mark.asyncio
async def test_a_stored_unknown_role_does_not_load_so_that_account_cannot_sign_in():
    from datetime import UTC, datetime

    from app.gateway.auth.repositories.sqlite import SQLiteUserRepository
    from deerflow.persistence.user.model import UserRow

    good, bad = str(uuid4()), str(uuid4())
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=[UserRow.__table__]))
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        async with session.begin():
            for user_id, role in ((good, "client"), (bad, "superuser")):
                session.add(UserRow(id=user_id, email=f"{role}@example.com", password_hash="x", system_role=role, needs_setup=False, token_version=0, created_at=datetime.now(UTC)))

    repo = SQLiteUserRepository(session_factory)
    assert (await repo.get_user_by_id(good)).system_role == "client"
    with pytest.raises(ValidationError):
        await repo.get_user_by_id(bad)
    await engine.dispose()


# -- exec and client are not admin --------------------------------------------


@pytest.mark.asyncio
async def test_only_the_admin_role_passes_the_admin_check():
    assert await is_admin_user(_request(system_role="admin")) is True
    for role in NOT_ADMIN:
        assert await is_admin_user(_request(system_role=role)) is False


@pytest.mark.asyncio
async def test_an_admin_pat_is_still_not_admin():
    assert await is_admin_user(_request(system_role="admin", auth_source=AUTH_SOURCE_PAT)) is False


@pytest.mark.parametrize("role", NOT_ADMIN)
@pytest.mark.asyncio
async def test_require_admin_user_answers_403_for_every_other_role(role):
    with pytest.raises(HTTPException) as denied:
        await require_admin_user(_request(system_role=role), detail="nope")
    assert denied.value.status_code == 403


def test_every_system_role_comparison_in_the_source_is_an_exact_admin_or_internal_check():
    """An `in ("admin", "exec")` anywhere would quietly make exec an admin."""
    backend = Path(__file__).resolve().parents[1]
    found = set()
    for root in (backend / "app", backend / "packages" / "harness" / "deerflow"):
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            assert not re.search(r"system_role\s+(not\s+)?in\b", text), f"set membership on system_role in {path}"
            for operator, literal in re.findall(r'system_role\s*(==|!=)\s*"(\w+)"', text):
                found.add((operator, literal))
    assert {literal for _, literal in found} == {"admin"}


@pytest.mark.parametrize("role", NOT_ADMIN)
@pytest.mark.parametrize(
    ("handler", "args"),
    [
        (admin_router.list_audit_events, ()),
        (cost_router.get_spend, ()),
        (managed_models.list_managed_models, ()),
    ],
)
@pytest.mark.asyncio
async def test_admin_only_handlers_answer_403_to_other_roles(handler, args, role):
    with pytest.raises(HTTPException) as denied:
        await handler(*args, _request(system_role=role))
    assert denied.value.status_code == 403


@pytest.mark.parametrize("role", NOT_ADMIN)
@pytest.mark.asyncio
async def test_an_exec_cannot_promote_itself_or_anyone_else(role):
    with pytest.raises(HTTPException) as denied:
        await admin_router.set_user_role("someone", admin_router.SetUserRoleRequest(system_role="admin"), _request(system_role=role, actor_id="someone"))
    assert denied.value.status_code == 403
    for handler in (admin_router.disable_user, admin_router.enable_user, admin_router.force_logout_user):
        with pytest.raises(HTTPException) as denied:
            await handler("someone", _request(system_role=role))
        assert denied.value.status_code == 403


# -- the admin role endpoint --------------------------------------------------


class _FakeProvider:
    def __init__(self, users: dict[str, User]) -> None:
        self.users = users

    async def get_user(self, user_id: str) -> User | None:
        return self.users.get(user_id)

    async def update_user(self, user: User) -> User:
        return user


@pytest_asyncio.fixture()
async def audit_repo():
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=[AuditEventRow.__table__]))
    yield AuditEventRepository(async_sessionmaker(engine, expire_on_commit=False))
    await engine.dispose()


@pytest.fixture()
def users(monkeypatch):
    store: dict[str, User] = {"target": User(id=uuid4(), email="target@example.com", password_hash="x", system_role="user", token_version=3)}
    monkeypatch.setattr(admin_router, "get_local_provider", lambda: _FakeProvider(store))
    monkeypatch.setattr(admin_router, "get_current_user_from_request", _actor)
    monkeypatch.setattr("app.gateway.authz._get_route_authorization_config", lambda: AuthorizationConfig())
    return store


async def _actor(request):
    return request.state.user


@pytest.mark.parametrize("role", ["exec", "client", "user", "admin"])
@pytest.mark.asyncio
async def test_an_admin_sets_any_role_and_the_change_is_audited(users, audit_repo, role):
    response = await admin_router.set_user_role("target", admin_router.SetUserRoleRequest(system_role=role), _request(system_role="admin", audit_repo=audit_repo))

    assert response.system_role == role
    assert users["target"].system_role == role
    assert users["target"].token_version == 3  # live read: no need to end sessions
    events, _ = await audit_repo.list(organization_id=None)
    assert [(e["action"], e["target_id"], e["details"]) for e in events] == [("admin.user.role_changed", "target", {"from": "user", "to": role})]


@pytest.mark.asyncio
async def test_an_admin_cannot_change_their_own_role(users):
    with pytest.raises(HTTPException) as refused:
        await admin_router.set_user_role("admin-1", admin_router.SetUserRoleRequest(system_role="client"), _request(system_role="admin"))
    assert refused.value.status_code == 400


@pytest.mark.asyncio
async def test_setting_the_role_of_a_missing_user_is_a_404(users):
    with pytest.raises(HTTPException) as missing:
        await admin_router.set_user_role("nobody", admin_router.SetUserRoleRequest(system_role="exec"), _request(system_role="admin"))
    assert missing.value.status_code == 404


def test_the_request_body_refuses_an_unknown_role_or_extra_fields():
    for body in ({"system_role": "superuser"}, {"system_role": "exec", "extra": 1}, {}):
        with pytest.raises(ValidationError):
            admin_router.SetUserRoleRequest(**body)


def _rbac(monkeypatch, roles: dict) -> None:
    config = AuthorizationConfig(enabled=True, default_role="user")
    provider = RbacAuthorizationProvider(roles=roles)
    monkeypatch.setattr("app.gateway.authz._get_route_authorization_config", lambda: config)
    monkeypatch.setattr("app.gateway.authz._get_cached_route_provider", lambda _config: provider)


@pytest.mark.asyncio
async def test_a_role_with_no_policy_block_is_refused_instead_of_locking_the_user_out(users, monkeypatch):
    _rbac(monkeypatch, {"user": {}, "admin": {}})
    with pytest.raises(HTTPException) as refused:
        await admin_router.set_user_role("target", admin_router.SetUserRoleRequest(system_role="client"), _request(system_role="admin"))
    assert refused.value.status_code == 409
    assert "authorization.provider.config.roles" in refused.value.detail
    assert users["target"].system_role == "user"


@pytest.mark.asyncio
async def test_a_defined_role_is_accepted_when_rbac_is_enabled(users, monkeypatch):
    _rbac(monkeypatch, {"user": {}, "admin": {}, "exec": {}})
    response = await admin_router.set_user_role("target", admin_router.SetUserRoleRequest(system_role="exec"), _request(system_role="admin"))
    assert response.system_role == "exec"
