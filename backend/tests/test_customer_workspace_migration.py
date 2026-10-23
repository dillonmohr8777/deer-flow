"""Explicit migration and pre-creator private history, with real tenant scoping."""

from types import SimpleNamespace

import pytest
from langgraph.store.memory import InMemoryStore
from org_isolation_fixtures import ORG_A, ORG_B, ORG_S, USER_A, USER_B, USER_C, acting_as, auth_headers, org_world  # noqa: F401
from sqlalchemy import func, select, update
from test_customer_workspace_invitations import PAYLOAD, _http, _setup

from app.gateway.routers import client_portal, workspaces
from deerflow.persistence.clients.model import ClientAssignmentRow
from deerflow.persistence.organizations.model import OrganizationMemberRow, OrganizationRow
from deerflow.persistence.thread_meta import MemoryThreadMetaStore, ThreadMetaRepository
from deerflow.persistence.user.model import UserRow
from deerflow.runtime.user_context import reset_current_user, set_current_user

pytestmark = pytest.mark.asyncio
PATH = "/api/client-portal/customer-workspaces/migrations"
BODY = {"client_id": PAYLOAD["client_id"], "user_id": USER_B, "name": "Synthetic dedicated workspace"}


async def _source(sf, monkeypatch):
    app = await _setup(sf, monkeypatch)
    app.include_router(workspaces.router)
    monkeypatch.setattr(workspaces, "get_session_factory", lambda: sf)
    async with sf() as session, session.begin():
        await session.execute(update(UserRow).where(UserRow.id == USER_B).values(system_role="client"))
        session.add(OrganizationMemberRow(organization_id=ORG_S, user_id=USER_B, role="client", status="active"))
        session.add(ClientAssignmentRow(client_id=BODY["client_id"], user_id=USER_B, organization_id=ORG_S, role="client_contact"))
    return app


async def test_admin_migrates_contact_and_preserves_private_membership(org_world, monkeypatch):  # noqa: F811
    app = await _source(org_world, monkeypatch)
    async with _http(app) as client:
        response = await client.post(PATH, headers=auth_headers(USER_A, ORG_S), json=BODY)
        assert response.status_code == 201, response.text
        target = response.json()["workspace_id"]
        assert target not in {ORG_A, ORG_B, ORG_S}
        assert (await client.get("/api/client-portal/clients", headers=auth_headers(USER_B, ORG_S))).status_code == 403
        assert (await client.get("/api/client-portal/clients", headers=auth_headers(USER_B, target))).json()["clients"] == [{"id": BODY["client_id"], "name": "Synthetic Alpha"}]
        assert (await client.post("/api/workspaces/select", headers=auth_headers(USER_B, ORG_S), json={"workspace_id": None})).status_code == 200
        assert (await client.get("/api/client-portal/clients", headers=auth_headers(USER_C, target))).status_code == 403
        assert (await client.post(PATH, headers=auth_headers(USER_A, ORG_S), json=BODY)).status_code == 409
    async with org_world() as session:
        assert (await session.get(OrganizationMemberRow, {"organization_id": ORG_S, "user_id": USER_B})).status == "inactive"
        assert (await session.get(OrganizationMemberRow, {"organization_id": ORG_B, "user_id": USER_B})).status == "active"
        assert (await session.get(ClientAssignmentRow, {"client_id": BODY["client_id"], "user_id": USER_B})).organization_id == target
        assert await session.scalar(select(func.count()).select_from(OrganizationRow).where(OrganizationRow.customer_client_id == BODY["client_id"])) == 1


@pytest.mark.parametrize("conflict", ["other_client", "other_tenant", "staff_membership", "staff_account", "wrong_agency", "nonadmin", "client_actor"])
async def test_migration_conflicts_are_atomic(org_world, monkeypatch, conflict):  # noqa: F811
    app = await _source(org_world, monkeypatch)
    async with org_world() as session, session.begin():
        if conflict == "other_client":
            session.add(ClientAssignmentRow(client_id="other-client", user_id=USER_B, organization_id=ORG_S, role="client_contact"))
        elif conflict == "other_tenant":
            session.add(OrganizationMemberRow(organization_id=ORG_A, user_id=USER_B, role="client", status="active"))
            # Give that foreign organization its own storage principal to prove shared scope is rejected.
            await session.execute(update(OrganizationRow).where(OrganizationRow.id == ORG_A).values(storage_user_id=USER_A))
        elif conflict == "staff_membership":
            await session.execute(update(OrganizationMemberRow).where(OrganizationMemberRow.organization_id == ORG_S, OrganizationMemberRow.user_id == USER_B).values(role="admin"))
        elif conflict == "staff_account":
            await session.execute(update(UserRow).where(UserRow.id == USER_B).values(system_role="admin"))
    async with _http(app) as client:
        response = await client.post(PATH, headers=auth_headers(USER_B if conflict == "client_actor" else USER_C if conflict == "nonadmin" else USER_A, ORG_A if conflict == "wrong_agency" else ORG_S), json=BODY)
        expected = {"nonadmin": 403, "client_actor": 403, "wrong_agency": 404, "staff_account": 422}.get(conflict, 409)
        assert response.status_code == expected, response.text
    async with org_world() as session:
        assert (await session.get(OrganizationMemberRow, {"organization_id": ORG_S, "user_id": USER_B})).status == "active"
        assert (await session.get(ClientAssignmentRow, {"client_id": BODY["client_id"], "user_id": USER_B})).organization_id == ORG_S
        assert await session.scalar(select(func.count()).select_from(OrganizationRow).where(OrganizationRow.customer_client_id.is_not(None))) == 0


async def test_migration_reuses_valid_dedicated_binding(org_world, monkeypatch):  # noqa: F811
    app = await _source(org_world, monkeypatch)
    async with _http(app) as client:
        created = await client.post("/api/client-portal/customer-workspaces/invitations", headers=auth_headers(USER_A, ORG_S), json=PAYLOAD)
        assert created.status_code == 201, created.text
        migrated = await client.post(PATH, headers=auth_headers(USER_A, ORG_S), json=BODY)
        assert migrated.status_code == 201, migrated.text
        assert migrated.json()["workspace_id"] == created.json()["workspace_id"]
    async with org_world() as session:
        assert await session.scalar(select(func.count()).select_from(OrganizationRow).where(OrganizationRow.customer_client_id == BODY["client_id"])) == 1


async def test_migration_failure_rolls_back_source_access(org_world, monkeypatch):  # noqa: F811
    app = await _source(org_world, monkeypatch)
    original = client_portal.validate_customer_workspace

    async def fail(*args, **kwargs):
        await original(*args, **kwargs)
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(client_portal, "validate_customer_workspace", fail)
    async with _http(app) as client:
        assert (await client.post(PATH, headers=auth_headers(USER_A, ORG_S), json=BODY)).status_code == 500
    async with org_world() as session:
        assert (await session.get(OrganizationMemberRow, {"organization_id": ORG_S, "user_id": USER_B})).status == "active"
        assert (await session.get(ClientAssignmentRow, {"client_id": BODY["client_id"], "user_id": USER_B})).organization_id == ORG_S
        assert await session.scalar(select(func.count()).select_from(OrganizationRow).where(OrganizationRow.customer_client_id.is_not(None))) == 0


@pytest.mark.parametrize("backend", ["sql", "memory"])
async def test_legacy_history_only_for_exact_private_owner(org_world, backend):  # noqa: F811
    store = ThreadMetaRepository(org_world) if backend == "sql" else MemoryThreadMetaStore(InMemoryStore())
    # These chats predate client creator stamps.
    for actor, org, name in [(USER_A, None, "foreign-private"), (USER_B, None, "own-private"), (USER_C, ORG_S, "agency-shared")]:
        with acting_as(actor, org):
            await store.create(name)
    await store.create("ownerless", user_id=None)
    with acting_as(USER_B):
        token = set_current_user(SimpleNamespace(id=USER_B, system_role="client"))
        try:
            assert (await store.get("own-private"))["client_actor_id"] is None
            assert {row["thread_id"] for row in await store.search()} == {"own-private"}
            assert await store.get("foreign-private") is None
            assert await store.get("ownerless") is None
            assert await store.get("agency-shared") is None
            assert await store.check_access("own-private", USER_B, require_existing=True)
            await store.update_display_name("own-private", "Still visible")
            assert (await store.get("own-private"))["display_name"] == "Still visible"
            assert not await store.claim_unowned("ownerless", USER_B)
        finally:
            reset_current_user(token)
    with acting_as(USER_B, ORG_S):
        token = set_current_user(SimpleNamespace(id=USER_B, system_role="client"))
        try:
            assert await store.get("agency-shared") is None
            assert await store.get("own-private") is None
            assert await store.search() == []
        finally:
            reset_current_user(token)
