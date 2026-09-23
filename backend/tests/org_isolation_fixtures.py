"""Shared organization-isolation world for M3 tests.

Lane 0 owns this module; lanes A-F import it instead of seeding their own orgs:

    from org_isolation_fixtures import ORG_A, ORG_S, USER_A, acting_as, auth_headers, org_world  # noqa: F401

The layout copies the production creation paths, so every organization id is
``private_organization_id(storage principal)`` just as in live data:

- users a, b, c are real logins, each the active owner of a private
  organization (A, B, C), as ``create_user`` builds them;
- S is a shared workspace (``app/gateway/routers/workspaces.py``
  ``create_workspace``): its storage principal ``s`` is a password-less users
  row with no membership anywhere, and S's id is ``private_organization_id(s)``;
- a owns S, c is an active S admin (invitees become admin), b is an outsider.

``org_world`` yields the session factory for repositories. It also points
``AuthMiddleware`` at this database and authenticates a request as the user
named in its ``access_token`` cookie, so an app built from ``AuthMiddleware``
plus the router under test enforces real membership. Send ``auth_headers``.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import deerflow.persistence.models  # noqa: F401 -- registers every table with Base.metadata
from deerflow.config.authorization_config import AuthorizationConfig
from deerflow.persistence.base import Base
from deerflow.persistence.organizations.identity import private_organization_id, private_organization_slug
from deerflow.persistence.organizations.model import OrganizationMemberRow, OrganizationRow
from deerflow.persistence.user.model import UserRow
from deerflow.runtime.user_context import (
    WorkspaceStorageContext,
    reset_current_user,
    reset_storage_context,
    set_current_user,
    set_storage_context,
)

USER_A, USER_B, USER_C = "user-a", "user-b", "user-c"
STORAGE_S = "storage-s"
ORG_A, ORG_B, ORG_C, ORG_S = (private_organization_id(user) for user in (USER_A, USER_B, USER_C, STORAGE_S))

# The storage principal AuthMiddleware selects in each organization.
STORAGE_USERS: dict[str, str] = {ORG_A: USER_A, ORG_B: USER_B, ORG_C: USER_C, ORG_S: STORAGE_S}

# (organization_id, user_id) -> role. Every membership starts active.
MEMBERSHIPS: dict[tuple[str, str], str] = {
    (ORG_A, USER_A): "owner",
    (ORG_B, USER_B): "owner",
    (ORG_C, USER_C): "owner",
    (ORG_S, USER_A): "owner",
    (ORG_S, USER_C): "admin",
}


def auth_headers(actor: str, organization_id: str | None = None) -> dict[str, str]:
    """Headers that make AuthMiddleware act as ``actor`` in ``organization_id``."""
    cookie = f"access_token={actor}"
    if organization_id is not None and organization_id != private_organization_id(actor):
        cookie += f"; deerflow_workspace={organization_id}"
    return {"Cookie": cookie}


@contextmanager
def acting_as(actor: str, organization_id: str | None = None):
    """Stamp the identity AuthMiddleware would, for repository-level tests."""
    organization_id = organization_id or private_organization_id(actor)
    user_token = set_current_user(SimpleNamespace(id=actor))
    storage_token = set_storage_context(
        WorkspaceStorageContext(
            actor_user_id=actor,
            organization_id=organization_id,
            storage_user_id=STORAGE_USERS[organization_id],
            role=MEMBERSHIPS.get((organization_id, actor)),
        )
    )
    try:
        yield
    finally:
        reset_storage_context(storage_token)
        reset_current_user(user_token)


async def _user_from_access_token(request):
    return SimpleNamespace(id=request.cookies["access_token"], system_role="user", email="org-world@example.com")


@pytest_asyncio.fixture()
async def org_world(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(UTC)
    async with session_factory() as session, session.begin():
        for user in (USER_A, USER_B, USER_C, STORAGE_S):
            # The storage principal has no password and is never issued a session.
            session.add(UserRow(id=user, email=f"{user}@example.com", password_hash=None, system_role="user", needs_setup=False, token_version=0, created_at=now))
        for user in (USER_A, USER_B, USER_C):
            session.add(OrganizationRow(id=private_organization_id(user), slug=private_organization_slug(user), name="Private organization", status="active", created_at=now, updated_at=now))
        session.add(OrganizationRow(id=ORG_S, slug=private_organization_slug(STORAGE_S), name="Shared S", status="active", storage_user_id=STORAGE_S, created_at=now, updated_at=now))
        for (organization_id, user), role in MEMBERSHIPS.items():
            session.add(OrganizationMemberRow(organization_id=organization_id, user_id=user, role=role, status="active", created_at=now, updated_at=now))

    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "")
    monkeypatch.setattr("deerflow.persistence.engine.get_session_factory", lambda: session_factory)
    monkeypatch.setattr("app.gateway.deps.get_current_user_from_request", _user_from_access_token)
    monkeypatch.setattr("app.gateway.authz._get_route_authorization_config", lambda: AuthorizationConfig())
    yield session_factory
    await engine.dispose()
