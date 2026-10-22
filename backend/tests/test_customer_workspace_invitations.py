"""Synthetic invite-first onboarding through real SQL and workspace authorization."""

import asyncio
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from org_isolation_fixtures import ORG_A, ORG_S, USER_A, USER_B, USER_C, auth_headers, org_world, org_world_pooled  # noqa: F401
from sqlalchemy import func, select, update
from starlette.responses import Response
from test_workspace_invitations import _request, _signed_in

from app.gateway.auth.config import AuthConfig
from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.routers import client_portal, invitations
from deerflow.config.authorization_config import AuthorizationConfig
from deerflow.persistence.clients.model import ClientAssignmentRow, ClientRow
from deerflow.persistence.organizations.invitation import InvitationRow
from deerflow.persistence.organizations.model import OrganizationMemberRow, OrganizationRow
from deerflow.persistence.user.model import UserRow

pytestmark = pytest.mark.asyncio
PATH = "/api/client-portal/customer-workspaces/invitations"
PAYLOAD = {"client_id": "synthetic-alpha", "email": "new-customer@example.com", "name": "Synthetic Alpha customer"}


async def _setup(sf, monkeypatch):
    async with sf() as session, session.begin():
        await session.execute(update(UserRow).where(UserRow.id == USER_A).values(system_role="admin"))
        session.add(ClientRow(id=PAYLOAD["client_id"], organization_id=ORG_S, display_name="Synthetic Alpha"))

    async def user(request):
        async with sf() as session:
            row = await session.get(UserRow, request.cookies["access_token"])
            return SimpleNamespace(id=row.id, system_role=row.system_role, email=row.email)

    monkeypatch.setattr("app.gateway.deps.get_current_user_from_request", user)
    monkeypatch.setattr(client_portal, "get_current_user_from_request", user)
    monkeypatch.setattr(invitations, "_session_factory", lambda: sf)
    monkeypatch.setattr(invitations, "role_has_policy", lambda role: True)
    monkeypatch.setattr("app.gateway.authz._get_route_authorization_config", lambda: AuthorizationConfig(invitations_frozen=False))
    monkeypatch.setattr("app.gateway.auth.config._auth_config", AuthConfig(jwt_secret="synthetic-customer-invitation-secret"))
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.include_router(client_portal.router)
    return app


def _http(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test")


async def _invite(client, payload=None, actor=USER_A, org=ORG_S):
    return await client.post(PATH, headers=auth_headers(actor, org), json=payload or PAYLOAD)


async def test_new_customer_accepts_bound_invite_without_agency_access(org_world, monkeypatch):  # noqa: F811
    app = await _setup(org_world, monkeypatch)
    async with _http(app) as client:
        created = await _invite(client)
        assert created.status_code == 201, created.text
        assert created.headers["cache-control"] == "no-store"
        data = created.json()
        accepted = await invitations.accept_invitation(invitations.AcceptInvitationRequest(token=data["token"], password="Synthetic-customer-password!"), _request(), Response())
        assert accepted.workspace_id == data["workspace_id"] != ORG_S
        async with org_world() as session:
            customer = await session.scalar(select(UserRow).where(UserRow.email == PAYLOAD["email"]))
            assert customer.system_role == "client"
            workspace = await session.get(OrganizationRow, accepted.workspace_id)
            storage = await session.get(UserRow, workspace.storage_user_id)
            assert workspace.customer_client_id == PAYLOAD["client_id"] and storage.password_hash is None
            assert await session.get(OrganizationMemberRow, {"organization_id": ORG_S, "user_id": customer.id}) is None
            membership = await session.get(OrganizationMemberRow, {"organization_id": workspace.id, "user_id": customer.id})
            assert membership.role == "client"
            assignment = await session.get(ClientAssignmentRow, {"client_id": PAYLOAD["client_id"], "user_id": customer.id})
            assert (assignment.organization_id, assignment.role) == (workspace.id, "client_contact")
            assert await session.scalar(select(func.count()).select_from(ClientRow)) == 1
        roster = await client.get("/api/client-portal/clients", headers=auth_headers(customer.id, workspace.id))
        assert roster.status_code == 200 and roster.json()["clients"] == [{"id": PAYLOAD["client_id"], "name": "Synthetic Alpha"}]
        assert (await client.get("/api/client-portal/clients", headers=auth_headers(customer.id, ORG_S))).status_code == 403


async def test_concurrent_retries_create_one_workspace_and_rotate_only_own_pending_link(org_world_pooled, monkeypatch):  # noqa: F811
    sf = org_world_pooled
    app = await _setup(sf, monkeypatch)
    original = client_portal._customer_client
    both_ready = asyncio.Event()
    entered = 0

    async def contend(*args, **kwargs):
        nonlocal entered
        entered += 1
        if entered == 2:
            both_ready.set()
        await both_ready.wait()
        return await original(*args, **kwargs)

    monkeypatch.setattr(client_portal, "_customer_client", contend)
    async with _http(app) as client:
        first, second = await asyncio.gather(_invite(client), _invite(client))
        assert first.status_code == second.status_code == 201, (first.text, second.text)
        one, two = first.json(), second.json()
        assert one["workspace_id"] == two["workspace_id"] and one["token"] != two["token"]
        monkeypatch.setattr(client_portal, "_customer_client", original)
        other = (await _invite(client, {**PAYLOAD, "email": "other-customer@example.com"})).json()
        await _invite(client)
    async with sf() as session:
        assert await session.scalar(select(func.count()).select_from(OrganizationRow).where(OrganizationRow.customer_client_id == PAYLOAD["client_id"])) == 1
        assert await session.scalar(select(func.count()).select_from(UserRow).where(UserRow.email.like("workspace-%@deerflow.invalid"))) == 1
        links = (await session.scalars(select(InvitationRow).where(InvitationRow.organization_id == one["workspace_id"], InvitationRow.email == PAYLOAD["email"]))).all()
        assert len(links) == 3 and sum(row.consumed_at is None for row in links) == 1
        assert (await session.get(InvitationRow, other["id"])).consumed_at is None


async def test_failure_rolls_back_workspace_storage_binding_and_rotation(org_world, monkeypatch):  # noqa: F811
    app = await _setup(org_world, monkeypatch)
    original = invitations._create_invitation_row

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("synthetic issuance failure")

    monkeypatch.setattr(invitations, "_create_invitation_row", fail)
    async with _http(app) as client:
        assert (await _invite(client)).status_code == 500
    async with org_world() as session:
        assert await session.scalar(select(func.count()).select_from(OrganizationRow).where(OrganizationRow.customer_client_id.is_not(None))) == 0
        assert await session.scalar(select(func.count()).select_from(UserRow).where(UserRow.email.like("workspace-%@deerflow.invalid"))) == 0
        assert await session.scalar(select(func.count()).select_from(InvitationRow)) == 0
    monkeypatch.setattr(invitations, "_create_invitation_row", original)
    async with _http(app) as client:
        first = (await _invite(client)).json()
        monkeypatch.setattr(invitations, "_create_invitation_row", fail)
        assert (await _invite(client)).status_code == 500
    async with org_world() as session:
        assert (await session.get(InvitationRow, first["id"])).consumed_at is None
        assert await session.scalar(select(func.count()).select_from(InvitationRow)) == 1


@pytest.mark.parametrize("actor,org,expected", [(USER_B, ORG_S, 403), (USER_C, ORG_S, 403), (USER_A, ORG_A, 404)])
async def test_requires_global_admin_selected_agency_and_canonical_client(org_world, monkeypatch, actor, org, expected):  # noqa: F811
    app = await _setup(org_world, monkeypatch)
    async with _http(app) as client:
        assert (await _invite(client, actor=actor, org=org)).status_code == expected
    async with org_world() as session:
        assert await session.scalar(select(func.count()).select_from(InvitationRow)) == 0


async def test_freeze_missing_policy_and_shared_membership_fail_without_orphans(org_world, monkeypatch):  # noqa: F811
    app = await _setup(org_world, monkeypatch)
    async with _http(app) as client:
        monkeypatch.setattr("app.gateway.authz._get_route_authorization_config", lambda: AuthorizationConfig(invitations_frozen=True))
        assert (await _invite(client)).status_code == 403
        monkeypatch.setattr("app.gateway.authz._get_route_authorization_config", lambda: AuthorizationConfig(invitations_frozen=False))
        monkeypatch.setattr(invitations, "role_has_policy", lambda role: False)
        assert (await _invite(client)).status_code == 409
        monkeypatch.setattr(invitations, "role_has_policy", lambda role: True)
        async with org_world() as session, session.begin():
            session.add(OrganizationMemberRow(organization_id=ORG_S, user_id=USER_B, role="client", status="active"))
        assert (await _invite(client, {**PAYLOAD, "email": "user-b@example.com"})).status_code == 409
    async with org_world() as session:
        assert await session.scalar(select(func.count()).select_from(OrganizationRow).where(OrganizationRow.customer_client_id.is_not(None))) == 0


@pytest.mark.parametrize("via", ["local", "sso"])
@pytest.mark.parametrize("system_role,expected", [("user", "client"), ("client", "client"), ("admin", "admin"), ("exec", "exec")])
async def test_existing_account_and_sso_contact_roles(org_world, monkeypatch, via, system_role, expected):  # noqa: F811
    app = await _setup(org_world, monkeypatch)
    async with org_world() as session, session.begin():
        await session.execute(update(UserRow).where(UserRow.id == USER_B).values(system_role=system_role))
    async with _http(app) as client:
        created = await _invite(client, {**PAYLOAD, "email": "user-b@example.com"})
        assert created.status_code == 201, created.text
        data = created.json()
    if via == "local":
        await invitations.accept_invitation(invitations.AcceptInvitationRequest(token=data["token"]), _signed_in(USER_B), Response())
    else:
        assert await invitations.join_invited_workspaces(_request(), user_id=USER_B, email="user-b@example.com") == data["workspace_id"]
    async with org_world() as session:
        assert (await session.get(UserRow, USER_B)).system_role == expected
        assignment = await session.get(ClientAssignmentRow, {"client_id": PAYLOAD["client_id"], "user_id": USER_B})
        assert (assignment.organization_id, assignment.role) == (data["workspace_id"], "client_contact")


@pytest.mark.parametrize("via", ["local", "sso"])
async def test_binding_or_account_changed_after_invite_rolls_back_acceptance(org_world, monkeypatch, via):  # noqa: F811
    app = await _setup(org_world, monkeypatch)
    async with _http(app) as client:
        created = (await _invite(client, {**PAYLOAD, "email": "user-b@example.com"})).json()
    async with org_world() as session, session.begin():
        session.add(ClientAssignmentRow(client_id="different-client", user_id=USER_B, organization_id=ORG_S, role="client_contact"))
    with pytest.raises(HTTPException) as blocked:
        if via == "local":
            await invitations.accept_invitation(invitations.AcceptInvitationRequest(token=created["token"]), _signed_in(USER_B), Response())
        else:
            await invitations.join_invited_workspaces(_request(), user_id=USER_B, email="user-b@example.com")
    assert blocked.value.status_code == 409
    async with org_world() as session:
        assert (await session.get(InvitationRow, created["id"])).consumed_at is None
        assert await session.get(OrganizationMemberRow, {"organization_id": created["workspace_id"], "user_id": USER_B}) is None
        assert (await session.get(UserRow, USER_B)).system_role == "user"


@pytest.mark.parametrize("agency_role", ["client", "member", "admin"])
async def test_sso_customer_does_not_join_other_pending_agency_links(org_world, monkeypatch, agency_role):  # noqa: F811
    app = await _setup(org_world, monkeypatch)
    async with _http(app) as client:
        data = (await _invite(client, {**PAYLOAD, "email": "user-b@example.com"})).json()
    # Deliberately newer: invitation ordering must not choose agency access.
    async with org_world() as session, session.begin():
        agency = await session.get(OrganizationRow, ORG_S)
        older = invitations._create_invitation_row(session, organization=agency, email="user-b@example.com", role=agency_role, actor_id=USER_A, now=invitations._now())
    assert await invitations.join_invited_workspaces(_request(), user_id=USER_B, email="user-b@example.com") == data["workspace_id"]
    with pytest.raises(HTTPException) as blocked:
        await invitations.accept_invitation(invitations.AcceptInvitationRequest(token=older.token), _signed_in(USER_B), Response())
    assert blocked.value.status_code == 409
    async with org_world() as session:
        assert (await session.get(InvitationRow, older.id)).consumed_at is None
        assert await session.get(OrganizationMemberRow, {"organization_id": ORG_S, "user_id": USER_B}) is None


async def test_sso_ambiguous_customer_invites_consume_nothing(org_world, monkeypatch):  # noqa: F811
    app = await _setup(org_world, monkeypatch)
    async with org_world() as session, session.begin():
        session.add(ClientRow(id="synthetic-beta", organization_id=ORG_S, display_name="Synthetic Beta"))
    async with _http(app) as client:
        first = (await _invite(client, {**PAYLOAD, "email": "user-b@example.com"})).json()
        second = (await _invite(client, {**PAYLOAD, "client_id": "synthetic-beta", "email": "user-b@example.com"})).json()
    with pytest.raises(HTTPException) as blocked:
        await invitations.join_invited_workspaces(_request(), user_id=USER_B, email="user-b@example.com")
    assert blocked.value.status_code == 409
    async with org_world() as session:
        for item in (first, second):
            assert (await session.get(InvitationRow, item["id"])).consumed_at is None
            assert await session.get(OrganizationMemberRow, {"organization_id": item["workspace_id"], "user_id": USER_B}) is None


@pytest.mark.parametrize("conflict", ["assignment", "duplicate_binding", "inactive_binding", "different_agency"])
async def test_existing_conflicts_do_not_create_another_workspace(org_world, monkeypatch, conflict):  # noqa: F811
    app = await _setup(org_world, monkeypatch)
    async with _http(app) as client:
        existing = (await _invite(client)).json()
        async with org_world() as session, session.begin():
            if conflict == "assignment":
                session.add(ClientAssignmentRow(client_id="other-canonical", user_id=USER_B, organization_id=ORG_S, role="client_contact"))
            elif conflict == "duplicate_binding":
                session.add(OrganizationRow(id="synthetic-conflicting-workspace", slug="synthetic-conflicting", name="Conflict", status="active", storage_user_id="synthetic-conflicting-storage", customer_client_id=PAYLOAD["client_id"]))
            elif conflict == "inactive_binding":
                await session.execute(update(OrganizationRow).where(OrganizationRow.id == existing["workspace_id"]).values(status="inactive"))
            else:
                await session.execute(update(ClientRow).where(ClientRow.id == PAYLOAD["client_id"]).values(organization_id=ORG_A))
        result = await _invite(client, {**PAYLOAD, "email": "user-b@example.com"})
        assert result.status_code == (404 if conflict == "different_agency" else 409), result.text
    async with org_world() as session:
        assert await session.scalar(select(func.count()).select_from(InvitationRow)) == 1
        assert await session.scalar(select(func.count()).select_from(UserRow).where(UserRow.email.like("workspace-%@deerflow.invalid"))) == 1


@pytest.mark.parametrize("guard", ["shared_membership", "assignment"])
async def test_legacy_provisioner_keeps_fresh_account_guard(org_world, monkeypatch, guard):  # noqa: F811
    app = await _setup(org_world, monkeypatch)
    async with org_world() as session, session.begin():
        await session.execute(update(UserRow).where(UserRow.id == USER_B).values(system_role="client"))
        if guard == "shared_membership":
            session.add(OrganizationMemberRow(organization_id=ORG_S, user_id=USER_B, role="client", status="active"))
        else:
            session.add(ClientAssignmentRow(client_id="other-client", user_id=USER_B, organization_id=ORG_S, role="client_contact"))
    async with _http(app) as client:
        result = await client.post("/api/client-portal/customer-workspaces", headers=auth_headers(USER_A, ORG_S), json={"client_id": PAYLOAD["client_id"], "user_id": USER_B, "name": PAYLOAD["name"]})
        assert result.status_code == 409, result.text
    async with org_world() as session:
        assert await session.scalar(select(func.count()).select_from(OrganizationRow).where(OrganizationRow.customer_client_id.is_not(None))) == 0


async def test_rotation_does_not_touch_consumed_or_other_role_links(org_world, monkeypatch):  # noqa: F811
    app = await _setup(org_world, monkeypatch)
    consumed = invitations._now()
    async with _http(app) as client:
        first = (await _invite(client)).json()
        async with org_world() as session, session.begin():
            await session.execute(update(InvitationRow).where(InvitationRow.id == first["id"]).values(consumed_at=consumed))
            workspace = await session.get(OrganizationRow, first["workspace_id"])
            other_role = invitations._create_invitation_row(session, organization=workspace, email=PAYLOAD["email"], role="member", actor_id=USER_A, now=invitations._now())
        assert (await _invite(client)).status_code == 201
    async with org_world() as session:
        assert invitations._as_utc((await session.get(InvitationRow, first["id"])).consumed_at) == consumed
        assert (await session.get(InvitationRow, other_role.id)).consumed_at is None
