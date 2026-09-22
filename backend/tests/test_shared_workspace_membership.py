"""Exercise membership enforcement through the actual HTTP middleware and SQL."""
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, Request

from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.routers import workspaces
from deerflow.config.authorization_config import AuthorizationConfig
from deerflow.persistence.organizations.identity import private_organization_id, private_organization_slug
from deerflow.persistence.organizations.model import OrganizationMemberRow, OrganizationRow
from deerflow.runtime.user_context import AUTO, resolve_user_id
from test_workspace_invitations import invitation_db, _seed_workspace  # noqa: F401


@pytest.mark.asyncio
async def test_two_members_share_content_identity_but_revocation_and_foreign_cookie_deny(invitation_db, monkeypatch):
    shared_id = await _seed_workspace(invitation_db, owner_id="actor-a")
    async with invitation_db() as session, session.begin():
        for actor in ("actor-a", "actor-b", "outsider"):
            private_id = private_organization_id(actor)
            session.add(OrganizationRow(id=private_id, slug=private_organization_slug(actor), name="Private", status="active"))
            session.add(OrganizationMemberRow(organization_id=private_id, user_id=actor, role="owner", status="active"))
        session.add(OrganizationMemberRow(organization_id=shared_id, user_id="actor-b", role="admin", status="active"))

    async def authenticated_actor(request):
        return SimpleNamespace(id=request.cookies["access_token"], system_role="user", email="test@example.com")

    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "")
    monkeypatch.setattr("app.gateway.deps.get_current_user_from_request", authenticated_actor)
    monkeypatch.setattr("deerflow.persistence.engine.get_session_factory", lambda: invitation_db)
    monkeypatch.setattr(workspaces, "get_session_factory", lambda: invitation_db)
    monkeypatch.setattr("app.gateway.authz._get_route_authorization_config", lambda: AuthorizationConfig())
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.include_router(workspaces.router)

    @app.get("/api/proof")
    async def proof(request: Request):
        return {"actor": str(request.state.user.id), "storage": resolve_user_id(AUTO)}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        async def read(actor, path="/api/proof"):
            return await client.get(path, headers={"Cookie": f"access_token={actor}; deerflow_workspace={shared_id}"})
        for actor in ("actor-a", "actor-b"):
            result = await read(actor)
            assert result.status_code == 200
            assert result.json() == {"actor": actor, "storage": "storage-owner"}
        assert (await read("outsider")).status_code == 403
        async with invitation_db() as session, session.begin():
            member = await session.get(OrganizationMemberRow, {"organization_id": shared_id, "user_id": "actor-b"})
            member.status = "revoked"
        assert (await read("actor-b")).status_code == 403
        # The revoked cookie cannot trap the user: selection/discovery remains accessible.
        listing = await read("actor-b", "/api/workspaces")
        assert listing.status_code == 200 and listing.json()["workspaces"] == []
        result = await client.post("/api/workspaces/select", headers={"Cookie": "access_token=actor-b"}, json={"workspace_id": shared_id})
        assert result.status_code == 404
