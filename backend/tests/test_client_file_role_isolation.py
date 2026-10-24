"""Exercise client file authorization through the real Gateway and SQL thread store."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from org_isolation_fixtures import USER_B, auth_headers, org_world  # noqa: F401
from sqlalchemy import update
from test_client_portal import BASE as PORTAL_BASE
from test_client_portal import CUSTOMER_ORG, CUSTOMER_STORAGE, _seed_bound_customer
from test_org_isolation_b_threads import world  # noqa: F401

from app.gateway.routers import client_portal
from deerflow.persistence.clients.model import ClientAssignmentRow
from deerflow.persistence.organizations.identity import private_organization_id, private_organization_slug
from deerflow.persistence.organizations.model import OrganizationMemberRow, OrganizationRow
from deerflow.persistence.thread_meta.model import ThreadMetaRow
from deerflow.persistence.user.model import UserRow

pytestmark = pytest.mark.asyncio

PEER_ACTOR = "00000000-0000-4000-8000-000000000002"
FOREIGN_ACTOR = "00000000-0000-4000-8000-000000000003"
FOREIGN_STORAGE = "00000000-0000-4000-8000-000000000004"
FOREIGN_ORG = private_organization_id(FOREIGN_STORAGE)


async def _seed_client_file_world(session_factory):
    """Reuse the canonical customer fixture and add two isolated synthetic contacts."""
    await _seed_bound_customer(session_factory)
    now = datetime.now(UTC)
    async with session_factory() as session, session.begin():
        await session.execute(update(UserRow).where(UserRow.id == USER_B).values(system_role="client"))
        session.add_all(
            [
                UserRow(id=PEER_ACTOR, email="peer-client@example.test", password_hash=None, system_role="client", needs_setup=False, token_version=0, created_at=now),
                UserRow(id=FOREIGN_ACTOR, email="foreign-client@example.test", password_hash=None, system_role="client", needs_setup=False, token_version=0, created_at=now),
                UserRow(id=FOREIGN_STORAGE, email="foreign-storage@example.test", password_hash=None, system_role="user", needs_setup=False, token_version=0, created_at=now),
                OrganizationRow(
                    id=FOREIGN_ORG,
                    slug=private_organization_slug(FOREIGN_STORAGE),
                    name="Synthetic foreign customer",
                    status="active",
                    storage_user_id=FOREIGN_STORAGE,
                    customer_client_id="client-b",
                    created_at=now,
                    updated_at=now,
                ),
                OrganizationMemberRow(organization_id=CUSTOMER_ORG, user_id=PEER_ACTOR, role="client", status="active", created_at=now, updated_at=now),
                OrganizationMemberRow(organization_id=FOREIGN_ORG, user_id=FOREIGN_ACTOR, role="client", status="active", created_at=now, updated_at=now),
                ClientAssignmentRow(client_id="client-a", user_id=PEER_ACTOR, organization_id=CUSTOMER_ORG, role="client_contact", created_at=now, updated_at=now),
                ClientAssignmentRow(client_id="client-b", user_id=FOREIGN_ACTOR, organization_id=FOREIGN_ORG, role="client_contact", created_at=now, updated_at=now),
            ]
        )
    async with session_factory() as session:
        customer = await session.get(OrganizationRow, CUSTOMER_ORG)
        foreign_customer = await session.get(OrganizationRow, FOREIGN_ORG)
        assert (customer.customer_client_id, customer.storage_user_id) == ("client-a", CUSTOMER_STORAGE)
        assert (foreign_customer.customer_client_id, foreign_customer.storage_user_id) == ("client-b", FOREIGN_STORAGE)
        for actor in (USER_B, PEER_ACTOR, FOREIGN_ACTOR):
            assert (await session.get(UserRow, actor)).system_role == "client"
        for organization_id, actor, client_id in ((CUSTOMER_ORG, USER_B, "client-a"), (CUSTOMER_ORG, PEER_ACTOR, "client-a"), (FOREIGN_ORG, FOREIGN_ACTOR, "client-b")):
            member = await session.get(OrganizationMemberRow, {"organization_id": organization_id, "user_id": actor})
            assignment = await session.get(ClientAssignmentRow, {"client_id": client_id, "user_id": actor})
            assert (member.role, member.status) == ("client", "active")
            assert (assignment.organization_id, assignment.role) == (organization_id, "client_contact")


async def _install_db_backed_test_auth(world_ctx, monkeypatch):
    """Use the fixture's fake cookie auth, with CLIENT roles read from synthetic SQL rows."""

    async def user_from_cookie(request):
        actor = request.cookies["access_token"]
        async with world_ctx.sf() as session:
            row = await session.get(UserRow, actor)
        assert row is not None
        return SimpleNamespace(id=row.id, system_role=row.system_role, email=row.email)

    monkeypatch.setattr("app.gateway.deps.get_current_user_from_request", user_from_cookie)
    monkeypatch.setattr(client_portal, "get_current_user_from_request", user_from_cookie)


async def _create_client_chat(world_ctx, actor, organization_id, client_id, submission_key):
    headers = auth_headers(actor, organization_id)
    composed = await world_ctx.client.post(
        PORTAL_BASE,
        headers=headers,
        json={
            "client_id": client_id,
            "submission_key": submission_key,
            "subject": "Synthetic file-isolation request",
            "body": "Use the synthetic records for this test only.",
        },
    )
    assert composed.status_code == 200, composed.text
    portal_thread_id = composed.json()["id"]
    chat = await world_ctx.client.post(f"{PORTAL_BASE}/{portal_thread_id}/chat", headers=headers)
    assert chat.status_code == 200, chat.text
    return portal_thread_id, chat.json()["chat_id"], headers


async def test_client_file_routes_are_bound_to_dedicated_customer_chat_actor(world, monkeypatch):  # noqa: F811
    """A CLIENT contact sees their durable chat files, not peer or foreign customer files."""
    await _seed_client_file_world(world.sf)
    await _install_db_backed_test_auth(world, monkeypatch)
    world.app.include_router(client_portal.router)

    portal_id, owned_thread, owned_headers = await _create_client_chat(world, USER_B, CUSTOMER_ORG, "client-a", "client-file-owner-20261024")
    _, peer_thread, _ = await _create_client_chat(world, PEER_ACTOR, CUSTOMER_ORG, "client-a", "client-file-peer-20261024")
    _, foreign_thread, _ = await _create_client_chat(world, FOREIGN_ACTOR, FOREIGN_ORG, "client-b", "client-file-foreign-20261024")

    async with world.sf() as session:
        owned_row = await session.get(ThreadMetaRow, owned_thread)
    assert owned_row is not None
    assert (owned_row.user_id, owned_row.organization_id, owned_row.client_actor_id) == (CUSTOMER_STORAGE, CUSTOMER_ORG, USER_B)

    owned_artifact = b"synthetic-client-owned-report"
    owned_path = world.outputs(owned_thread, CUSTOMER_STORAGE) / "owned-report.txt"
    owned_path.parent.mkdir(parents=True, exist_ok=True)
    owned_path.write_bytes(owned_artifact)
    own_artifact_response = await world.client.get(
        f"/api/threads/{owned_thread}/artifacts/mnt/user-data/outputs/owned-report.txt",
        headers=owned_headers,
    )
    assert (own_artifact_response.status_code, own_artifact_response.content) == (200, owned_artifact)

    own_upload = b"synthetic-client-owned-source"
    upload_response = await world.request(
        USER_B,
        "POST",
        f"/api/threads/{owned_thread}/uploads",
        {"files": {"files": ("owned-source.txt", own_upload, "text/plain")}},
        org=CUSTOMER_ORG,
    )
    assert upload_response.status_code == 200, upload_response.text
    assert upload_response.json()["success"] is True
    assert (world.paths.sandbox_uploads_dir(owned_thread, user_id=CUSTOMER_STORAGE) / "owned-source.txt").read_bytes() == own_upload
    own_listing = await world.request(USER_B, "GET", f"/api/threads/{owned_thread}/uploads/list", org=CUSTOMER_ORG)
    assert own_listing.status_code == 200, own_listing.text
    assert "owned-source.txt" in {item["filename"] for item in own_listing.json()["files"]}

    # A stale or mismatched workspace binding cannot create/reopen the portal chat.
    async with world.sf() as session, session.begin():
        await session.execute(update(OrganizationRow).where(OrganizationRow.id == CUSTOMER_ORG).values(customer_client_id="client-b"))
    try:
        mismatched = await world.client.post(f"{PORTAL_BASE}/{portal_id}/chat", headers=owned_headers)
        assert mismatched.status_code == 404, mismatched.text
    finally:
        async with world.sf() as session, session.begin():
            await session.execute(update(OrganizationRow).where(OrganizationRow.id == CUSTOMER_ORG).values(customer_client_id="client-a"))

    unknown = await world.client.get(
        "/api/threads/client-role-unknown-file-thread/artifacts/mnt/user-data/outputs/missing.txt",
        headers=owned_headers,
    )
    assert unknown.status_code == 404

    peer_artifact = b"synthetic-peer-client-private"
    peer_artifact_path = world.outputs(peer_thread, CUSTOMER_STORAGE) / "peer-private.txt"
    peer_artifact_path.parent.mkdir(parents=True, exist_ok=True)
    peer_artifact_path.write_bytes(peer_artifact)
    peer_upload_path = world.paths.sandbox_uploads_dir(peer_thread, user_id=CUSTOMER_STORAGE) / "peer-private.txt"
    peer_upload_path.parent.mkdir(parents=True, exist_ok=True)
    peer_upload_path.write_bytes(b"synthetic-peer-upload-private")
    peer_files_before = {path.name: path.read_bytes() for path in peer_upload_path.parent.iterdir() if path.is_file()}

    peer_get = await world.client.get(
        f"/api/threads/{peer_thread}/artifacts/mnt/user-data/outputs/peer-private.txt",
        headers=owned_headers,
    )
    assert peer_get.status_code == 404 and peer_artifact not in peer_get.content
    peer_list = await world.client.get(f"/api/threads/{peer_thread}/uploads/list", headers=owned_headers)
    assert peer_list.status_code == 404
    peer_post = await world.client.post(
        f"/api/threads/{peer_thread}/uploads",
        headers=owned_headers,
        files={"files": ("blocked-client-upload.txt", b"must-not-write", "text/plain")},
    )
    assert peer_post.status_code == 404
    peer_delete = await world.client.delete(f"/api/threads/{peer_thread}/uploads/peer-private.txt", headers=owned_headers)
    assert peer_delete.status_code == 404
    assert {path.name: path.read_bytes() for path in peer_upload_path.parent.iterdir() if path.is_file()} == peer_files_before
    assert peer_upload_path.read_bytes() == b"synthetic-peer-upload-private"

    foreign_artifact = b"synthetic-foreign-customer-private"
    foreign_artifact_path = world.outputs(foreign_thread, FOREIGN_STORAGE) / "foreign-private.txt"
    foreign_artifact_path.parent.mkdir(parents=True, exist_ok=True)
    foreign_artifact_path.write_bytes(foreign_artifact)
    foreign_upload_path = world.paths.sandbox_uploads_dir(foreign_thread, user_id=FOREIGN_STORAGE) / "foreign-private.txt"
    foreign_upload_path.parent.mkdir(parents=True, exist_ok=True)
    foreign_upload_path.write_bytes(b"synthetic-foreign-upload-private")
    assert foreign_artifact_path.read_bytes() == foreign_artifact
    assert foreign_upload_path.read_bytes() == b"synthetic-foreign-upload-private"

    foreign_get = await world.client.get(
        f"/api/threads/{foreign_thread}/artifacts/mnt/user-data/outputs/foreign-private.txt",
        headers=owned_headers,
    )
    assert foreign_get.status_code == 404 and foreign_artifact not in foreign_get.content
    foreign_list = await world.client.get(f"/api/threads/{foreign_thread}/uploads/list", headers=owned_headers)
    assert foreign_list.status_code == 404
    foreign_post = await world.client.post(
        f"/api/threads/{foreign_thread}/uploads",
        headers=owned_headers,
        files={"files": ("blocked-foreign-upload.txt", b"must-not-write", "text/plain")},
    )
    assert foreign_post.status_code == 404
    foreign_delete = await world.client.delete(f"/api/threads/{foreign_thread}/uploads/foreign-private.txt", headers=owned_headers)
    assert foreign_delete.status_code == 404
    assert foreign_artifact_path.read_bytes() == foreign_artifact
    assert foreign_upload_path.read_bytes() == b"synthetic-foreign-upload-private"


async def test_upload_before_create_cannot_be_claimed_by_another_client_actor(world, monkeypatch):  # noqa: F811
    """A client-created row must not adopt a peer's upload-only thread id and bytes."""
    await _seed_client_file_world(world.sf)
    await _install_db_backed_test_auth(world, monkeypatch)

    thread_id = "client-upload-claim-isolation-20261024"
    preupload = b"synthetic-first-client-upload"
    async with world.sf() as session:
        assert await session.get(ThreadMetaRow, thread_id) is None
    uploaded = await world.request(
        USER_B,
        "POST",
        f"/api/threads/{thread_id}/uploads",
        {"files": {"files": ("client-source.txt", preupload, "text/plain")}},
        org=CUSTOMER_ORG,
    )
    assert uploaded.status_code == 200, uploaded.text
    preuploaded_path = world.paths.sandbox_uploads_dir(thread_id, user_id=CUSTOMER_STORAGE) / "client-source.txt"
    assert preuploaded_path.read_bytes() == preupload
    async with world.sf() as session:
        preupload_row = await session.get(ThreadMetaRow, thread_id)

    claim = await world.request(PEER_ACTOR, "POST", "/api/threads", {"thread_id": thread_id}, org=CUSTOMER_ORG)
    async with world.sf() as session:
        claimed_row = await session.get(ThreadMetaRow, thread_id)
    peer_read = await world.client.get(
        f"/api/threads/{thread_id}/artifacts/mnt/user-data/uploads/client-source.txt",
        headers=auth_headers(PEER_ACTOR, CUSTOMER_ORG),
    )
    original_read = await world.client.get(
        f"/api/threads/{thread_id}/artifacts/mnt/user-data/uploads/client-source.txt",
        headers=auth_headers(USER_B, CUSTOMER_ORG),
    )
    preupload_binding = (preupload_row.user_id, preupload_row.organization_id, preupload_row.client_actor_id) if preupload_row is not None else None
    claimed_binding = (claimed_row.user_id, claimed_row.organization_id, claimed_row.client_actor_id) if claimed_row is not None else None
    assert claim.status_code in {404, 409} and peer_read.status_code == 404 and original_read.status_code == 200 and original_read.content == preupload, (
        f"preupload_row={preupload_binding}, claim={claim.status_code}, claimed_row={claimed_binding}, peer_read=({peer_read.status_code}, {peer_read.content!r}), original_read=({original_read.status_code}, {original_read.content!r})"
    )
