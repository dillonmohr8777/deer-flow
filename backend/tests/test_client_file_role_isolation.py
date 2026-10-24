"""Exercise client file authorization through the real Gateway and SQL thread store."""

import asyncio
import threading
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from langgraph.store.memory import InMemoryStore
from org_isolation_fixtures import ORG_S, STORAGE_S, USER_A, USER_B, USER_C, auth_headers
from org_isolation_fixtures import org_world_pooled as org_world  # noqa: F401
from sqlalchemy import select, update
from test_client_portal import BASE as PORTAL_BASE
from test_client_portal import CUSTOMER_ORG, CUSTOMER_STORAGE, _seed_bound_customer
from test_org_isolation_b_threads import (
    _put_checkpoint,
    world,  # noqa: F401
)

from app.gateway import services
from app.gateway.deps import get_config
from app.gateway.routers import client_portal, uploads
from deerflow.config.app_config import AppConfig, set_app_config
from deerflow.config.run_ownership_config import RunOwnershipConfig
from deerflow.persistence.clients.model import ClientAssignmentRow
from deerflow.persistence.organizations.identity import private_organization_id, private_organization_slug
from deerflow.persistence.organizations.model import OrganizationMemberRow, OrganizationRow
from deerflow.persistence.projects.model import ProjectRow
from deerflow.persistence.run import RunRepository, RunRow
from deerflow.persistence.thread_meta.base import THREAD_UPLOAD_RESERVATION_METADATA_KEY
from deerflow.persistence.thread_meta.memory import MemoryThreadMetaStore
from deerflow.persistence.thread_meta.model import ThreadMetaRow
from deerflow.persistence.user.model import UserRow
from deerflow.runtime import ConflictError, RunManager, ThreadOperationKind
from deerflow.runtime.user_context import get_effective_actor_user_id

pytestmark = pytest.mark.asyncio

PEER_ACTOR = "00000000-0000-4000-8000-000000000002"
FOREIGN_ACTOR = "00000000-0000-4000-8000-000000000003"
FOREIGN_STORAGE = "00000000-0000-4000-8000-000000000004"
FOREIGN_ORG = private_organization_id(FOREIGN_STORAGE)


def _enable_synthetic_client_runs():
    set_app_config(
        AppConfig.model_validate(
            {
                "sandbox": {"use": "deerflow.community.aio_sandbox:AioSandboxProvider", "network": {"mode": "isolated"}},
                "models": [{"name": "synthetic-local", "use": "langchain_core.language_models.fake:FakeListLLM", "model": "synthetic-no-provider", "admission_route": "local"}],
                "momobot_max": {"enabled": True, "model": "synthetic-local", "base_model": "synthetic-local"},
            }
        )
    )


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


@pytest.mark.parametrize("system_role", ["client", "user"])
async def test_upload_before_create_cannot_be_claimed_by_another_client_actor(world, monkeypatch, system_role):  # noqa: F811
    """A client-created row must not adopt a peer's upload-only thread id and bytes."""
    await _seed_client_file_world(world.sf)
    if system_role == "user":
        async with world.sf() as session, session.begin():
            await session.execute(update(UserRow).where(UserRow.id.in_((USER_B, PEER_ACTOR))).values(system_role="user"))
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
    assert preupload_row is not None
    assert (preupload_row.user_id, preupload_row.organization_id, preupload_row.client_actor_id) == (CUSTOMER_STORAGE, CUSTOMER_ORG, USER_B)
    assert (await world.request(PEER_ACTOR, "GET", f"/api/threads/{thread_id}/uploads/list", org=CUSTOMER_ORG)).status_code == 404

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

    async with world.sf() as session, session.begin():
        session.add(ProjectRow(id="client-upload-project", user_id=CUSTOMER_STORAGE, organization_id=CUSTOMER_ORG, name="Synthetic upload project", status="active"))
    invalid = await world.request(USER_B, "POST", "/api/threads", {"thread_id": thread_id, "project_id": "missing-project"}, org=CUSTOMER_ORG)
    assert invalid.status_code == 404
    created = await world.request(
        USER_B,
        "POST",
        "/api/threads",
        {"thread_id": thread_id, "assistant_id": "momobot-max", "project_id": "client-upload-project", "metadata": {"source": "upload-first", THREAD_UPLOAD_RESERVATION_METADATA_KEY: "forged"}},
        org=CUSTOMER_ORG,
    )
    assert created.status_code == 200, created.text
    assert created.json()["metadata"] == {"source": "upload-first", "deerflow_project_id": "client-upload-project"}
    assert "upload_reserved" not in created.json()
    checkpoint = await world.checkpointer.aget_tuple({"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}})
    assert checkpoint is not None
    assert THREAD_UPLOAD_RESERVATION_METADATA_KEY not in checkpoint.metadata
    again = await world.request(USER_B, "POST", "/api/threads", {"thread_id": thread_id}, org=CUSTOMER_ORG)
    assert again.status_code == 200 and again.json() == created.json()
    async with world.sf() as session:
        final_row = await session.get(ThreadMetaRow, thread_id)
        assert final_row.incarnation == preupload_row.incarnation
        assert final_row.client_actor_id == USER_B
        assert (final_row.assistant_id, final_row.project_id) == ("momobot-max", "client-upload-project")
        assert THREAD_UPLOAD_RESERVATION_METADATA_KEY not in final_row.metadata_json
    assert preuploaded_path.read_bytes() == preupload

    patched = await world.request(USER_B, "PATCH", f"/api/threads/{thread_id}", {"metadata": {THREAD_UPLOAD_RESERVATION_METADATA_KEY: final_row.incarnation}}, org=CUSTOMER_ORG)
    assert patched.status_code == 200, patched.text
    forged = await world.request(USER_B, "POST", "/api/threads", {"thread_id": thread_id, "metadata": {"replacement": "must-not-reset"}}, org=CUSTOMER_ORG)
    assert forged.json()["metadata"] == created.json()["metadata"]


@pytest.mark.parametrize("backend", ["sql", "memory"])
async def test_concurrent_client_uploads_reserve_one_actor_without_resetting_thread(world, monkeypatch, backend):  # noqa: F811
    await _seed_client_file_world(world.sf)
    await _install_db_backed_test_auth(world, monkeypatch)
    if backend == "memory":
        world.app.state.thread_store = MemoryThreadMetaStore(InMemoryStore())
    thread_id = "client-concurrent-upload-reservation"

    async def upload(actor, filename, content):
        return await world.request(actor, "POST", f"/api/threads/{thread_id}/uploads", {"files": {"files": (filename, content, "text/plain")}}, org=CUSTOMER_ORG)

    actors = (USER_B, PEER_ACTOR)
    responses = await asyncio.gather(*(upload(actor, f"{index}.txt", f"actor-{index}".encode()) for index, actor in enumerate(actors)))
    assert sum(response.status_code == 200 for response in responses) == 1 and all(response.status_code in {200, 404, 409} for response in responses), [(response.status_code, response.text) for response in responses]
    winner = next(index for index, response in enumerate(responses) if response.status_code == 200)
    actor = actors[winner]
    directory = world.paths.sandbox_uploads_dir(thread_id, user_id=CUSTOMER_STORAGE)
    assert {path.name: path.read_bytes() for path in directory.iterdir()} == {f"{winner}.txt": f"actor-{winner}".encode()}
    creations = await asyncio.gather(*(world.request(actor, "POST", "/api/threads", {"thread_id": thread_id, "metadata": {"kept": value}}, org=CUSTOMER_ORG) for value in ("first", "second")))
    assert [created.status_code for created in creations] == [200, 200], [created.text for created in creations]
    assert creations[0].json() == creations[1].json()
    before = creations[0].json()
    own_responses = await asyncio.gather(upload(actor, "next-a.txt", b"a"), upload(actor, "next-b.txt", b"b"))
    for response, filename, content in zip(own_responses, ("next-a.txt", "next-b.txt"), (b"a", b"b"), strict=True):
        assert response.status_code in {200, 409}, response.text
        if response.status_code == 409:
            retried_upload = await upload(actor, filename, content)
            assert retried_upload.status_code == 200, retried_upload.text
    assert {path.name: path.read_bytes() for path in directory.iterdir()} == {f"{winner}.txt": f"actor-{winner}".encode(), "next-a.txt": b"a", "next-b.txt": b"b"}
    after = await world.request(actor, "POST", "/api/threads", {"thread_id": thread_id}, org=CUSTOMER_ORG)
    assert after.json() == before
    peer = await world.request(actors[1 - winner], "POST", "/api/threads", {"thread_id": thread_id}, org=CUSTOMER_ORG)
    assert peer.status_code == 404


@pytest.mark.parametrize("backend", ["sql", "memory"])
@pytest.mark.parametrize("legacy_kind", ["scoped", "unscoped", "empty", "staging", "symlink"])
async def test_legacy_upload_directories_are_never_adopted(world, monkeypatch, backend, legacy_kind):  # noqa: F811
    await _seed_client_file_world(world.sf)
    await _install_db_backed_test_auth(world, monkeypatch)
    if backend == "memory":
        world.app.state.thread_store = MemoryThreadMetaStore(InMemoryStore())
    thread_id = f"unknown-upload-{legacy_kind}"
    directory = world.paths.sandbox_uploads_dir(thread_id, user_id=None if legacy_kind == "unscoped" else CUSTOMER_STORAGE)
    if legacy_kind == "symlink":
        target = world.root / "unknown-upload-target"
        target.mkdir()
        (target / "unknown.txt").write_bytes(b"unknown-owner")
        directory.parent.mkdir(parents=True)
        try:
            directory.symlink_to(target, target_is_directory=True)
        except OSError as exc:
            if getattr(exc, "winerror", None) == 1314:
                pytest.skip("Windows symlink privilege is not available")
            raise
    else:
        directory.mkdir(parents=True)
        if legacy_kind != "empty":
            (directory / (".upload-unknown.part" if legacy_kind == "staging" else "unknown.txt")).write_bytes(b"unknown-owner")
    before = {path.name: path.read_bytes() for path in directory.iterdir()}
    for actor in (USER_B, PEER_ACTOR):
        probes = [
            ("POST", "/api/threads", {"thread_id": thread_id}),
            ("PUT", f"/api/threads/{thread_id}/goal", {"objective": "must not adopt"}),
            ("POST", "/api/runs/wait", {"config": {"configurable": {"thread_id": thread_id}}, "assistant_id": "lead_agent", "input": {"messages": [{"role": "user", "content": "must not run"}]}}),
            ("POST", f"/api/threads/{thread_id}/uploads", {"files": {"files": ("new.txt", b"must-not-write")}}),
            ("GET", f"/api/threads/{thread_id}/uploads/list", None),
            ("GET", f"/api/threads/{thread_id}/artifacts/mnt/user-data/uploads/unknown.txt", None),
        ]
        for method, path, body in probes:
            response = await world.request(actor, method, path, body, org=CUSTOMER_ORG)
            assert response.status_code == 404, (backend, legacy_kind, actor, method, path, response.status_code, response.text)
    assert {path.name: path.read_bytes() for path in directory.iterdir()} == before
    assert await world.app.state.thread_store.get(thread_id, user_id=None) is None
    assert await world.checkpointer.aget_tuple({"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}) is None


async def test_shared_staff_upload_before_create_remains_shared_and_checkpoint_orphans_deny(world):  # noqa: F811
    thread_id = "staff-precreate-upload"
    uploaded = await world.request(USER_A, "POST", f"/api/threads/{thread_id}/uploads", {"files": {"files": ("staff.txt", b"shared-staff")}}, org=ORG_S)
    assert uploaded.status_code == 200, uploaded.text
    created = await world.request(USER_C, "POST", "/api/threads", {"thread_id": thread_id}, org=ORG_S)
    assert created.status_code == 200, created.text
    read = await world.request(USER_C, "GET", f"/api/threads/{thread_id}/artifacts/mnt/user-data/uploads/staff.txt", org=ORG_S)
    assert (read.status_code, read.content) == (200, b"shared-staff")
    async with world.sf() as session:
        row = await session.get(ThreadMetaRow, thread_id)
        assert (row.user_id, row.organization_id, row.client_actor_id) == (STORAGE_S, ORG_S, None)
    orphan = "thread-orphan"
    denied = await world.request(USER_A, "POST", f"/api/threads/{orphan}/uploads", {"files": {"files": ("no.txt", b"must-not-write")}})
    assert denied.status_code == 404
    assert not world.paths.thread_dir(orphan, user_id=USER_A).exists()


@pytest.mark.parametrize("backend", ["sql", "memory"])
async def test_reserved_goal_and_stateless_run_keep_ownership_and_existing_checkpoints(world, monkeypatch, backend):  # noqa: F811
    if backend == "memory":
        world.app.state.thread_store = MemoryThreadMetaStore(InMemoryStore())
    for suffix in ("goal", "run"):
        thread_id = f"reserved-staff-{suffix}"
        upload = await world.request(USER_A, "POST", f"/api/threads/{thread_id}/uploads", {"files": {"files": ("source.txt", b"keep-source")}}, org=ORG_S)
        assert upload.status_code == 200, upload.text
        if suffix == "goal":
            response = await world.request(USER_A, "PUT", f"/api/threads/{thread_id}/goal", {"objective": "keep this goal"}, org=ORG_S)
        else:
            response = await world.request(
                USER_A, "POST", "/api/runs/wait", {"config": {"configurable": {"thread_id": thread_id}}, "assistant_id": "lead_agent", "input": {"messages": [{"role": "user", "content": "synthetic offline run"}]}}, org=ORG_S
            )
        assert response.status_code == 200, response.text
        if suffix == "run":
            # The fixture's run transport stub does not execute a graph/checkpoint.
            await _put_checkpoint(world.checkpointer, thread_id)
        config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
        before = await world.checkpointer.aget_tuple(config)
        prior = await world.request(USER_C, "GET", f"/api/threads/{thread_id}", org=ORG_S)
        created = await world.request(USER_C, "POST", "/api/threads", {"thread_id": thread_id, "assistant_id": "must-not-replace", "metadata": {"replace": "must-not-reset"}}, org=ORG_S)
        assert created.status_code == 200, created.text
        assert created.json()["metadata"] == prior.json()["metadata"]
        after = await world.checkpointer.aget_tuple(config)
        assert before == after
        assert (world.paths.sandbox_uploads_dir(thread_id, user_id=STORAGE_S) / "source.txt").read_bytes() == b"keep-source"
        assert THREAD_UPLOAD_RESERVATION_METADATA_KEY not in str(created.json())


async def test_failed_upload_keeps_its_reservation_without_partial_files(world, monkeypatch):  # noqa: F811
    await _seed_client_file_world(world.sf)
    await _install_db_backed_test_auth(world, monkeypatch)
    world.app.dependency_overrides[get_config] = lambda: AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}, "uploads": {"max_file_size": 2}})
    thread_id = "client-failed-upload-reservation"
    response = await world.request(USER_B, "POST", f"/api/threads/{thread_id}/uploads", {"files": {"files": ("large.txt", b"oversize")}}, org=CUSTOMER_ORG)
    assert response.status_code == 413, response.text
    directory = world.paths.sandbox_uploads_dir(thread_id, user_id=CUSTOMER_STORAGE)
    assert list(directory.iterdir()) == []
    denied = await world.request(PEER_ACTOR, "POST", "/api/threads", {"thread_id": thread_id}, org=CUSTOMER_ORG)
    assert denied.status_code == 404
    own = await world.request(USER_B, "POST", "/api/threads", {"thread_id": thread_id}, org=CUSTOMER_ORG)
    assert own.status_code == 200, own.text


@pytest.mark.parametrize("backend", ["sql", "memory"])
async def test_first_client_stateless_run_finalizes_upload_metadata_without_reparenting(world, monkeypatch, backend):  # noqa: F811
    await _seed_client_file_world(world.sf)
    await _install_db_backed_test_auth(world, monkeypatch)
    _enable_synthetic_client_runs()
    if backend == "memory":
        world.app.state.thread_store = MemoryThreadMetaStore(InMemoryStore())
    thread_id = "client-upload-first-stateless-run"
    uploaded = await world.request(USER_B, "POST", f"/api/threads/{thread_id}/uploads", {"files": {"files": ("source.txt", b"admitted-client-source")}}, org=CUSTOMER_ORG)
    assert uploaded.status_code == 200, uploaded.text
    if backend == "sql":
        async with world.sf() as session, session.begin():
            session.add(ProjectRow(id="client-run-project", user_id=CUSTOMER_STORAGE, organization_id=CUSTOMER_ORG, name="Synthetic run project", status="active"))
        moved = await world.request(USER_C, "POST", f"/api/threads/{thread_id}/move", {"project_id": "client-run-project"}, org=CUSTOMER_ORG)
        assert moved.status_code == 200, moved.text
    response = await world.request(
        USER_B,
        "POST",
        "/api/runs/wait",
        {
            "config": {"configurable": {"thread_id": thread_id}},
            "assistant_id": "momobot-max",
            "metadata": {"admitted": "first-run", "deerflow_project_id": "must-not-reparent", THREAD_UPLOAD_RESERVATION_METADATA_KEY: "forged"},
            "input": {"messages": [{"role": "user", "content": "Synthetic offline admission only"}]},
        },
        org=CUSTOMER_ORG,
    )
    assert response.status_code == 200, response.text
    visible = await world.request(USER_B, "GET", f"/api/threads/{thread_id}", org=CUSTOMER_ORG)
    assert visible.status_code == 200, visible.text
    metadata = visible.json()["metadata"]
    assert metadata["admitted"] == "first-run"
    assert metadata.get("deerflow_project_id") == ("client-run-project" if backend == "sql" else None)
    assert THREAD_UPLOAD_RESERVATION_METADATA_KEY not in metadata
    assert "upload_reserved" not in visible.json()
    if backend == "sql":
        async with world.sf() as session:
            row = await session.get(ThreadMetaRow, thread_id)
            assert (row.user_id, row.client_actor_id, row.assistant_id, row.project_id) == (CUSTOMER_STORAGE, USER_B, "momobot-max", "client-run-project")
            assert THREAD_UPLOAD_RESERVATION_METADATA_KEY not in row.metadata_json
    retried = await world.request(USER_B, "POST", "/api/threads", {"thread_id": thread_id, "assistant_id": "must-not-replace", "metadata": {"admitted": "must-not-reset"}}, org=CUSTOMER_ORG)
    assert retried.status_code == 200 and retried.json()["metadata"] == metadata
    peer = await world.request(PEER_ACTOR, "GET", f"/api/threads/{thread_id}/artifacts/mnt/user-data/uploads/source.txt", org=CUSTOMER_ORG)
    assert peer.status_code == 404
    original = await world.request(USER_B, "GET", f"/api/threads/{thread_id}/artifacts/mnt/user-data/uploads/source.txt", org=CUSTOMER_ORG)
    assert (original.status_code, original.content) == (200, b"admitted-client-source")


async def test_stale_stateless_admission_cannot_run_after_another_client_reserves_upload(world, monkeypatch):  # noqa: F811
    await _seed_client_file_world(world.sf)
    await _install_db_backed_test_auth(world, monkeypatch)
    _enable_synthetic_client_runs()
    thread_id = "client-stale-run-upload-race"
    checked_missing = asyncio.Event()
    continue_admission = asyncio.Event()
    original_check = world.threads.check_access
    original_worker = services.run_agent
    worker_actors = []
    paused = False

    async def pause_after_real_check(checked_thread, user_id, *, require_existing=False):
        nonlocal paused
        allowed = await original_check(checked_thread, user_id, require_existing=require_existing)
        if checked_thread == thread_id and get_effective_actor_user_id() == PEER_ACTOR and not paused:
            paused = True
            assert allowed is True
            checked_missing.set()
            await continue_admission.wait()
        return allowed

    async def record_transport_worker(*args, **kwargs):
        worker_actors.append(get_effective_actor_user_id())
        return await original_worker(*args, **kwargs)

    monkeypatch.setattr(world.threads, "check_access", pause_after_real_check)
    monkeypatch.setattr(services, "run_agent", record_transport_worker)
    stale_run = asyncio.create_task(
        world.request(
            PEER_ACTOR,
            "POST",
            "/api/runs/wait",
            {"assistant_id": "momobot-max", "config": {"configurable": {"thread_id": thread_id}}, "input": {"messages": [{"role": "user", "content": "Synthetic stale admission"}]}},
            org=CUSTOMER_ORG,
        )
    )
    try:
        await asyncio.wait_for(checked_missing.wait(), timeout=10)
        uploaded = await world.request(USER_B, "POST", f"/api/threads/{thread_id}/uploads", {"files": {"files": ("source.txt", b"first-client-race-source")}}, org=CUSTOMER_ORG)
        assert uploaded.status_code == 200, uploaded.text
    finally:
        continue_admission.set()
    response = await asyncio.wait_for(stale_run, timeout=15)
    assert response.status_code == 404 and worker_actors == [], (response.status_code, response.text, worker_actors)
    async with world.sf() as session:
        row = await session.get(ThreadMetaRow, thread_id)
        assert (row.user_id, row.organization_id, row.client_actor_id) == (CUSTOMER_STORAGE, CUSTOMER_ORG, USER_B)
    peer = await world.request(PEER_ACTOR, "GET", f"/api/threads/{thread_id}/artifacts/mnt/user-data/uploads/source.txt", org=CUSTOMER_ORG)
    original = await world.request(USER_B, "GET", f"/api/threads/{thread_id}/artifacts/mnt/user-data/uploads/source.txt", org=CUSTOMER_ORG)
    assert peer.status_code == 404
    assert (original.status_code, original.content) == (200, b"first-client-race-source")


@pytest.mark.parametrize("backend", ["sql", "memory"])
@pytest.mark.parametrize("data_root", ["outputs", "workspace", "staging"])
async def test_legacy_thread_data_cannot_be_claimed_or_served(world, monkeypatch, backend, data_root):  # noqa: F811
    await _seed_client_file_world(world.sf)
    await _install_db_backed_test_auth(world, monkeypatch)
    if backend == "memory":
        world.app.state.thread_store = MemoryThreadMetaStore(InMemoryStore())
    thread_id = f"unknown-thread-{data_root}"
    directory = world.paths.sandbox_user_data_dir(thread_id, user_id=CUSTOMER_STORAGE) / data_root
    directory.mkdir(parents=True)
    sentinel = f"synthetic-unknown-owner-{data_root}".encode()
    path = directory / "unknown.txt"
    path.write_bytes(sentinel)
    assert path.read_bytes() == sentinel
    async with world.sf() as session:
        assert await session.get(ThreadMetaRow, thread_id) is None
    claimed = await world.request(PEER_ACTOR, "POST", "/api/threads", {"thread_id": thread_id}, org=CUSTOMER_ORG)
    read = await world.request(PEER_ACTOR, "GET", f"/api/threads/{thread_id}/artifacts/mnt/user-data/{data_root}/unknown.txt", org=CUSTOMER_ORG)
    assert claimed.status_code == 404 and read.status_code == 404 and sentinel not in read.content, (claimed.status_code, read.status_code, read.content)
    assert await world.app.state.thread_store.get(thread_id, user_id=None) is None
    assert path.read_bytes() == sentinel


async def test_inflight_upload_blocks_delete_and_recreation_until_files_are_finished(world, monkeypatch):  # noqa: F811
    await _seed_client_file_world(world.sf)
    await _install_db_backed_test_auth(world, monkeypatch)
    thread_id = "client-inflight-upload-delete-recreate"
    payload = b"synthetic-original-actor-inflight-upload"
    reserved = asyncio.Event()
    proceed = asyncio.Event()
    original_reservation = uploads._reserve_upload_thread

    async def pause_after_real_reservation(candidate, request):
        await original_reservation(candidate, request)
        if candidate == thread_id:
            reserved.set()
            await asyncio.wait_for(proceed.wait(), timeout=20)

    monkeypatch.setattr(uploads, "_reserve_upload_thread", pause_after_real_reservation)
    pending = asyncio.create_task(
        world.request(
            USER_B,
            "POST",
            f"/api/threads/{thread_id}/uploads",
            {"files": [("files", ("actor-a-private.txt", payload, "text/plain")), ("files", ("second.txt", b"second-original-file", "text/plain"))]},
            org=CUSTOMER_ORG,
        )
    )
    try:
        await asyncio.wait_for(reserved.wait(), timeout=10)
        async with world.sf() as session:
            row = await session.get(ThreadMetaRow, thread_id)
            incarnation = row.incarnation
            assert (row.user_id, row.organization_id, row.client_actor_id) == (CUSTOMER_STORAGE, CUSTOMER_ORG, USER_B)
            active_operations = len((await session.scalars(select(RunRow).where(RunRow.thread_id == thread_id, RunRow.operation_kind != "run"))).all())
        assert not world.paths.thread_dir(thread_id, user_id=CUSTOMER_STORAGE).exists()
        other_manager = RunManager(store=RunRepository(world.sf), worker_id="synthetic-other-gateway")
        with pytest.raises(ConflictError):
            async with other_manager.reserve_thread_operation(thread_id, kind=ThreadOperationKind.delete, user_id=CUSTOMER_STORAGE):
                pytest.fail("A second manager bypassed the durable upload reservation")
        with pytest.raises(ConflictError):
            await other_manager.create_or_reject(thread_id, user_id=CUSTOMER_STORAGE, multitask_strategy="interrupt")
        deleted = await world.request(USER_B, "DELETE", f"/api/threads/{thread_id}", org=CUSTOMER_ORG)
        claimed = await world.request(PEER_ACTOR, "POST", "/api/threads", {"thread_id": thread_id}, org=CUSTOMER_ORG)
    finally:
        proceed.set()
        uploaded = await asyncio.wait_for(pending, timeout=15)
    peer_read = await world.request(PEER_ACTOR, "GET", f"/api/threads/{thread_id}/artifacts/mnt/user-data/uploads/actor-a-private.txt", org=CUSTOMER_ORG)
    original_read = await world.request(USER_B, "GET", f"/api/threads/{thread_id}/artifacts/mnt/user-data/uploads/actor-a-private.txt", org=CUSTOMER_ORG)
    listing = await world.request(USER_B, "GET", f"/api/threads/{thread_id}/uploads/list", org=CUSTOMER_ORG)
    assert (deleted.status_code, claimed.status_code, uploaded.status_code, peer_read.status_code, original_read.status_code, original_read.content, listing.status_code, active_operations) == (409, 404, 200, 404, 200, payload, 200, 1), (
        deleted.status_code,
        claimed.status_code,
        uploaded.status_code,
        peer_read.status_code,
        peer_read.content,
        original_read.status_code,
        active_operations,
    )
    assert {item["filename"] for item in listing.json()["files"]} == {"actor-a-private.txt", "second.txt"}
    async with world.sf() as session:
        row = await session.get(ThreadMetaRow, thread_id)
        assert row.client_actor_id == USER_B and row.incarnation == incarnation
        assert (await session.scalars(select(RunRow).where(RunRow.thread_id == thread_id, RunRow.operation_kind != "run"))).all() == []
    later_delete = await world.request(USER_B, "DELETE", f"/api/threads/{thread_id}", org=CUSTOMER_ORG)
    assert later_delete.status_code == 200, later_delete.text
    assert not world.paths.thread_dir(thread_id, user_id=CUSTOMER_STORAGE).exists()
    recreated = await world.request(PEER_ACTOR, "POST", "/api/threads", {"thread_id": thread_id}, org=CUSTOMER_ORG)
    assert recreated.status_code == 200, recreated.text
    async with world.sf() as session:
        row = await session.get(ThreadMetaRow, thread_id)
        assert row.client_actor_id == PEER_ACTOR and row.incarnation != incarnation
    assert (await world.request(PEER_ACTOR, "GET", f"/api/threads/{thread_id}/artifacts/mnt/user-data/uploads/actor-a-private.txt", org=CUSTOMER_ORG)).status_code == 404
    assert (await world.request(PEER_ACTOR, "GET", f"/api/threads/{thread_id}/uploads/list", org=CUSTOMER_ORG)).json()["files"] == []


async def test_rejected_upload_holds_admission_through_cleanup_and_releases_it(world, monkeypatch):  # noqa: F811
    await _seed_client_file_world(world.sf)
    await _install_db_backed_test_auth(world, monkeypatch)
    thread_id = "client-upload-rejected-cleanup"
    kept = await world.request(USER_B, "POST", f"/api/threads/{thread_id}/uploads", {"files": {"files": ("keep.txt", b"existing-owned-file", "text/plain")}}, org=CUSTOMER_ORG)
    assert kept.status_code == 200, kept.text
    world.app.dependency_overrides[get_config] = lambda: AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}, "uploads": {"max_file_size": 2}})
    cleanup_started = threading.Event()
    finish_cleanup = threading.Event()
    original_cleanup = uploads._cleanup_uploaded_paths

    def paused_cleanup(paths):
        cleanup_started.set()
        assert finish_cleanup.wait(20), "test cleanup barrier was not released"
        original_cleanup(paths)

    monkeypatch.setattr(uploads, "_cleanup_uploaded_paths", paused_cleanup)
    pending = asyncio.create_task(world.request(USER_B, "POST", f"/api/threads/{thread_id}/uploads", {"files": [("files", ("temporary.txt", b"x", "text/plain")), ("files", ("oversize.txt", b"oversize", "text/plain"))]}, org=CUSTOMER_ORG))
    try:
        assert await asyncio.to_thread(cleanup_started.wait, 10)
        during_cleanup = await world.request(USER_B, "DELETE", f"/api/threads/{thread_id}", org=CUSTOMER_ORG)
        assert during_cleanup.status_code == 409, during_cleanup.text
        async with world.sf() as session:
            assert len((await session.scalars(select(RunRow).where(RunRow.thread_id == thread_id, RunRow.operation_kind != "run"))).all()) == 1
    finally:
        finish_cleanup.set()
        rejected = await asyncio.wait_for(pending, timeout=15)
    assert rejected.status_code == 413, rejected.text
    directory = world.paths.sandbox_uploads_dir(thread_id, user_id=CUSTOMER_STORAGE)
    assert {path.name: path.read_bytes() for path in directory.iterdir()} == {"keep.txt": b"existing-owned-file"}
    async with world.sf() as session:
        assert (await session.scalars(select(RunRow).where(RunRow.thread_id == thread_id, RunRow.operation_kind != "run"))).all() == []
    deleted = await world.request(USER_B, "DELETE", f"/api/threads/{thread_id}", org=CUSTOMER_ORG)
    assert deleted.status_code == 200, deleted.text


async def test_cancelled_upload_drains_file_work_before_releasing_durable_admission(world, monkeypatch):  # noqa: F811
    await _seed_client_file_world(world.sf)
    await _install_db_backed_test_auth(world, monkeypatch)
    thread_id = "client-upload-cancellation-drain"
    payload = b"synthetic-cancelled-owned-upload"
    write_started = threading.Event()
    finish_write = threading.Event()
    released = asyncio.Event()
    holder = None
    original_write = uploads._write_upload_chunk
    original_reservation = uploads.reserve_upload_write

    def paused_write(upload_temp, chunk):
        write_started.set()
        assert finish_write.wait(20), "test file worker barrier was not released"
        original_write(upload_temp, chunk)

    @asynccontextmanager
    async def observed_reservation(candidate, request):
        nonlocal holder
        holder = asyncio.current_task()
        try:
            async with original_reservation(candidate, request):
                yield
        finally:
            released.set()

    monkeypatch.setattr(uploads, "_write_upload_chunk", paused_write)
    monkeypatch.setattr(uploads, "reserve_upload_write", observed_reservation)
    pending = asyncio.create_task(world.request(USER_B, "POST", f"/api/threads/{thread_id}/uploads", {"files": {"files": ("source.txt", payload, "text/plain")}}, org=CUSTOMER_ORG))
    try:
        assert await asyncio.to_thread(write_started.wait, 10)
        assert holder is not None
        holder.cancel()
        await asyncio.sleep(0)
        holder.cancel()
        await asyncio.sleep(0)
        assert not released.is_set()
        blocked_delete = await world.request(USER_B, "DELETE", f"/api/threads/{thread_id}", org=CUSTOMER_ORG)
        assert blocked_delete.status_code == 409, blocked_delete.text
        blocked_claim = await world.request(PEER_ACTOR, "POST", "/api/threads", {"thread_id": thread_id}, org=CUSTOMER_ORG)
        assert blocked_claim.status_code == 404, blocked_claim.text
        async with world.sf() as session:
            assert len((await session.scalars(select(RunRow).where(RunRow.thread_id == thread_id, RunRow.operation_kind != "run"))).all()) == 1
    finally:
        finish_write.set()
        await asyncio.wait_for(released.wait(), timeout=15)
        await asyncio.wait_for(asyncio.gather(pending, return_exceptions=True), timeout=15)
    assert (world.paths.sandbox_uploads_dir(thread_id, user_id=CUSTOMER_STORAGE) / "source.txt").read_bytes() == payload
    async with world.sf() as session:
        assert (await session.scalars(select(RunRow).where(RunRow.thread_id == thread_id, RunRow.operation_kind != "run"))).all() == []
    deleted = await world.request(USER_B, "DELETE", f"/api/threads/{thread_id}", org=CUSTOMER_ORG)
    assert deleted.status_code == 200, deleted.text
    recreated = await world.request(PEER_ACTOR, "POST", "/api/threads", {"thread_id": thread_id}, org=CUSTOMER_ORG)
    assert recreated.status_code == 200, recreated.text
    peer_read = await world.request(PEER_ACTOR, "GET", f"/api/threads/{thread_id}/artifacts/mnt/user-data/uploads/source.txt", org=CUSTOMER_ORG)
    assert peer_read.status_code == 404


async def test_expired_upload_stays_held_while_old_file_worker_drains(world, monkeypatch):  # noqa: F811
    await _seed_client_file_world(world.sf)
    await _install_db_backed_test_auth(world, monkeypatch)
    ownership = RunOwnershipConfig(heartbeat_enabled=True, lease_seconds=30, grace_seconds=0)
    first_manager = RunManager(store=RunRepository(world.sf), worker_id="synthetic-upload-owner", run_ownership_config=ownership)
    second_manager = RunManager(store=RunRepository(world.sf), worker_id="synthetic-upload-peer", run_ownership_config=ownership)
    world.app.state.run_manager = first_manager
    thread_id = "client-expired-upload-held"
    payload = b"synthetic-expired-old-owner-private-upload"
    prepare_started = threading.Event()
    finish_prepare = threading.Event()
    original_prepare = uploads._prepare_upload_destination

    def paused_prepare(directory, filename):
        if filename == "actor-a-private.txt":
            prepare_started.set()
            assert finish_prepare.wait(25), "test expired-upload barrier was not released"
        return original_prepare(directory, filename)

    monkeypatch.setattr(uploads, "_prepare_upload_destination", paused_prepare)
    pending = asyncio.create_task(world.request(USER_B, "POST", f"/api/threads/{thread_id}/uploads", {"files": {"files": ("actor-a-private.txt", payload, "text/plain")}}, org=CUSTOMER_ORG))
    try:
        assert await asyncio.to_thread(prepare_started.wait, 10)
        expired = datetime.now(UTC) - timedelta(hours=1)
        async with world.sf() as session, session.begin():
            operation = (await session.scalars(select(RunRow).where(RunRow.thread_id == thread_id, RunRow.operation_kind != "run"))).one()
            operation_id = operation.run_id
            operation.lease_expires_at = expired
            original_incarnation = (await session.get(ThreadMetaRow, thread_id)).incarnation
        first_manager._runs[operation_id].lease_expires_at = expired.isoformat()
        recovered = await second_manager.reconcile_orphaned_inflight_runs(error="Synthetic expired-upload probe")
        await first_manager._renew_leases()
        world.app.state.run_manager = second_manager
        deleted = await world.request(USER_B, "DELETE", f"/api/threads/{thread_id}", org=CUSTOMER_ORG)
        claimed = await world.request(PEER_ACTOR, "POST", "/api/threads", {"thread_id": thread_id}, org=CUSTOMER_ORG)
        # On the vulnerable schedule a legitimate peer upload recreates its own
        # directory, which the old offloaded prepare would otherwise reuse.
        if deleted.status_code == 200 and claimed.status_code == 200:
            peer_upload = await world.request(PEER_ACTOR, "POST", f"/api/threads/{thread_id}/uploads", {"files": {"files": ("peer.txt", b"peer-new-incarnation")}}, org=CUSTOMER_ORG)
            assert peer_upload.status_code == 200, peer_upload.text
    finally:
        finish_prepare.set()
        uploaded = await asyncio.wait_for(pending, timeout=15)
    peer_read = await world.request(PEER_ACTOR, "GET", f"/api/threads/{thread_id}/artifacts/mnt/user-data/uploads/actor-a-private.txt", org=CUSTOMER_ORG)
    original_read = await world.request(USER_B, "GET", f"/api/threads/{thread_id}/artifacts/mnt/user-data/uploads/actor-a-private.txt", org=CUSTOMER_ORG)
    assert (len(recovered), deleted.status_code, claimed.status_code, peer_read.status_code, original_read.status_code, original_read.content) == (0, 409, 404, 404, 200, payload), (
        len(recovered),
        deleted.status_code,
        claimed.status_code,
        uploaded.status_code,
        peer_read.status_code,
        peer_read.content,
        original_read.status_code,
    )
    async with world.sf() as session:
        row = await session.get(ThreadMetaRow, thread_id)
        assert row.client_actor_id == USER_B and row.incarnation == original_incarnation
        assert await session.get(RunRow, operation_id) is None
    later_delete = await world.request(USER_B, "DELETE", f"/api/threads/{thread_id}", org=CUSTOMER_ORG)
    assert later_delete.status_code == 200, later_delete.text
    recreated = await world.request(PEER_ACTOR, "POST", "/api/threads", {"thread_id": thread_id}, org=CUSTOMER_ORG)
    assert recreated.status_code == 200, recreated.text
    assert (await world.request(PEER_ACTOR, "GET", f"/api/threads/{thread_id}/artifacts/mnt/user-data/uploads/actor-a-private.txt", org=CUSTOMER_ORG)).status_code == 404
