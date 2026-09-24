"""Membership revocation: a user removed from a shared workspace immediately
loses both read and write access through the routes that grant it.

Existing coverage before this file (grepped, not duplicated here):
  - tests/test_shared_workspace_membership.py proves the generic
    AuthMiddleware + storage-identity gate 403s any route once
    OrganizationMemberRow.status flips to "revoked", using a stub /api/proof
    route plus the real /api/workspaces listing/selection routes.
  - tests/test_workspace_branding.py::test_revoked_member_loses_branding_access
    proves a revoked member's GET (read) on /api/workspaces/{id}/branding
    404s.
  - tests/test_workspace_invitations.py covers a revoked *invitation issuer*
    (an already-consumed invitation's creator going inactive), not a live
    member's own session being revoked mid-session.

Gaps this file fills:
  1. Branding WRITE (PUT/DELETE) for a revoked admin was untested — only the
     read path had a regression test. An admin who loses membership must
     also lose the ability to overwrite or reset workspace branding.
  2. Invitation creation (POST /api/v1/auth/invitations) does its own
     in-handler membership check (`_active_shared_workspace_member`)
     independent of AuthMiddleware/require_permission — it was untested
     against a revoked admin trying to invite new members into a workspace
     they no longer belong to.

Runs the real AuthMiddleware, the real invitations/workspace_branding
routers, and real SQL (disposable in-memory SQLite) — mirroring the existing
test_shared_workspace_membership.py / test_workspace_branding.py style.
"""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.routers import invitations, workspace_branding, workspaces
from deerflow.config.authorization_config import AuthorizationConfig
from deerflow.persistence.base import Base
from deerflow.persistence.organizations.branding import OrganizationBrandingRow
from deerflow.persistence.organizations.identity import private_organization_id, private_organization_slug
from deerflow.persistence.organizations.invitation import InvitationRow
from deerflow.persistence.organizations.model import OrganizationMemberRow, OrganizationRow
from deerflow.persistence.user.model import UserRow

SHARED_ID = "revocation-workspace-1"
ADMIN = "actor-admin"
OWNER = "actor-owner"


@pytest_asyncio.fixture()
async def membership_db(monkeypatch):
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync: Base.metadata.create_all(
                sync,
                tables=[
                    # Organization resolution also checks users.disabled_at.
                    UserRow.__table__,
                    OrganizationRow.__table__,
                    OrganizationMemberRow.__table__,
                    OrganizationBrandingRow.__table__,
                    InvitationRow.__table__,
                ],
            )
        )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session, session.begin():
        session.add(OrganizationRow(id=SHARED_ID, slug="revocation-co", name="Revocation Co", status="active", storage_user_id="storage-owner"))
        session.add(OrganizationMemberRow(organization_id=SHARED_ID, user_id=OWNER, role="owner", status="active"))
        session.add(OrganizationMemberRow(organization_id=SHARED_ID, user_id=ADMIN, role="admin", status="active"))
        for actor in (OWNER, ADMIN):
            private_id = private_organization_id(actor)
            session.add(OrganizationRow(id=private_id, slug=private_organization_slug(actor), name="Private", status="active", storage_user_id=actor))
            session.add(OrganizationMemberRow(organization_id=private_id, user_id=actor, role="owner", status="active"))

    async def authenticated_actor(request):
        return SimpleNamespace(id=request.cookies["access_token"], system_role="user", email="test@example.com")

    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "")
    monkeypatch.setattr("app.gateway.deps.get_current_user_from_request", authenticated_actor)
    monkeypatch.setattr("deerflow.persistence.engine.get_session_factory", lambda: session_factory)
    monkeypatch.setattr(workspaces, "get_session_factory", lambda: session_factory)
    monkeypatch.setattr(invitations, "_session_factory", lambda: session_factory)
    monkeypatch.setattr("app.gateway.authz._get_route_authorization_config", lambda: AuthorizationConfig(invitations_frozen=False))

    yield session_factory
    await engine.dispose()


@pytest_asyncio.fixture()
async def client(membership_db):
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.include_router(workspaces.router)
    app.include_router(workspace_branding.router)
    app.include_router(invitations.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        yield http


def _as(actor: str) -> dict[str, str]:
    return {"Cookie": f"access_token={actor}"}


async def _revoke(session_factory, user_id: str) -> None:
    async with session_factory() as session, session.begin():
        member = await session.get(OrganizationMemberRow, {"organization_id": SHARED_ID, "user_id": user_id})
        member.status = "revoked"


@pytest.mark.asyncio
async def test_active_admin_can_write_branding(client):
    """Sanity baseline: an active admin's write succeeds before revocation."""
    result = await client.put(
        f"/api/workspaces/{SHARED_ID}/branding",
        headers=_as(ADMIN),
        json={"brand_name": "Before Revoke", "treatment": "current"},
    )
    assert result.status_code == 200
    assert result.json()["brand_name"] == "Before Revoke"


@pytest.mark.asyncio
async def test_revoked_admin_loses_branding_write_access(client, membership_db):
    """WRITE gap: a revoked admin must not still be able to overwrite or
    reset workspace branding, mirroring the already-covered read case."""
    baseline = await client.put(
        f"/api/workspaces/{SHARED_ID}/branding",
        headers=_as(ADMIN),
        json={"brand_name": "Before Revoke", "treatment": "current"},
    )
    assert baseline.status_code == 200

    await _revoke(membership_db, ADMIN)

    put_after_revoke = await client.put(
        f"/api/workspaces/{SHARED_ID}/branding",
        headers=_as(ADMIN),
        json={"brand_name": "After Revoke", "treatment": "current", "expected_version": baseline.json()["version"]},
    )
    assert put_after_revoke.status_code == 404

    delete_after_revoke = await client.delete(
        f"/api/workspaces/{SHARED_ID}/branding?expected_version={baseline.json()['version']}",
        headers=_as(ADMIN),
    )
    assert delete_after_revoke.status_code == 404

    # The write did not silently apply: an active member still sees the
    # pre-revocation value, not "After Revoke".
    still_intact = await client.get(f"/api/workspaces/{SHARED_ID}/branding", headers=_as(OWNER))
    assert still_intact.status_code == 200
    assert still_intact.json()["brand_name"] == "Before Revoke"


@pytest.mark.asyncio
async def test_revoked_admin_cannot_invite_new_members(client, membership_db):
    """Invitation creation performs its own membership check independent of
    AuthMiddleware/require_permission; a revoked admin must not be able to
    invite new members into a workspace they no longer belong to."""
    baseline = await client.post(
        "/api/v1/auth/invitations",
        headers=_as(ADMIN),
        json={"organization_id": SHARED_ID, "email": "before-revoke@example.com"},
    )
    assert baseline.status_code == 201

    await _revoke(membership_db, ADMIN)

    after_revoke = await client.post(
        "/api/v1/auth/invitations",
        headers=_as(ADMIN),
        json={"organization_id": SHARED_ID, "email": "after-revoke@example.com"},
    )
    assert after_revoke.status_code == 403
