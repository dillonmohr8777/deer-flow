"""Offline org oversight through real SQLite, auth middleware and UUID users."""

import sqlite3
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from org_isolation_fixtures import auth_headers
from org_isolation_fixtures import org_world_pooled as org_world  # noqa: F401
from sqlalchemy import event, update
from sqlalchemy.orm import Session

from app.gateway.approval_adapters import execute_approved
from app.gateway.auth.models import User
from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.routers import approvals
from deerflow.persistence.approvals import PendingActionRepository
from deerflow.persistence.audit_events import AuditEventRepository
from deerflow.persistence.organizations.identity import private_organization_id, private_organization_slug
from deerflow.persistence.organizations.model import OrganizationMemberRow, OrganizationRow
from deerflow.persistence.user.model import UserRow
from deerflow.runtime.user_context import WorkspaceStorageContext, reset_current_user, reset_storage_context, set_current_user, set_storage_context

OWNER, ADMIN, MEMBER, FOREIGN, STORAGE = [str(UUID(int=n)) for n in range(101, 106)]
ORG = private_organization_id(STORAGE)
FOREIGN_ORG = private_organization_id(FOREIGN)
USERS = {actor: User(id=UUID(actor), email=f"qa{n}@example.com", system_role="user") for n, actor in enumerate((OWNER, ADMIN, MEMBER, FOREIGN))}


@contextmanager
def acting(actor, organization=ORG, *, context_actor=None):
    user_token = set_current_user(USERS[actor])
    storage_token = set_storage_context(WorkspaceStorageContext(actor_user_id=context_actor or actor, organization_id=organization, storage_user_id=STORAGE if organization == ORG else actor))
    try:
        yield
    finally:
        reset_storage_context(storage_token)
        reset_current_user(user_token)


@pytest_asyncio.fixture
async def world(org_world, monkeypatch):  # noqa: F811
    now = datetime.now(UTC)
    async with org_world() as session, session.begin():
        for actor in (*USERS, STORAGE):
            session.add(UserRow(id=actor, email=f"{actor}@example.test", system_role="user", needs_setup=False, token_version=0, created_at=now))
        for actor in USERS:
            session.add(OrganizationRow(id=private_organization_id(actor), slug=private_organization_slug(actor), name="Private QA", status="active", created_at=now, updated_at=now))
            session.add(OrganizationMemberRow(organization_id=private_organization_id(actor), user_id=actor, role="owner", status="active", created_at=now, updated_at=now))
        session.add(OrganizationRow(id=ORG, slug=private_organization_slug(STORAGE), name="Shared QA", storage_user_id=STORAGE, status="active", created_at=now, updated_at=now))
        for actor, role in ((OWNER, "owner"), (ADMIN, "admin"), (MEMBER, "member")):
            session.add(OrganizationMemberRow(organization_id=ORG, user_id=actor, role=role, status="active", created_at=now, updated_at=now))

    async def authenticate(request):
        return USERS[request.cookies["access_token"]]

    monkeypatch.setattr("app.gateway.deps.get_current_user_from_request", authenticate)
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.state.pending_action_repo = PendingActionRepository(org_world)
    app.state.audit_repo = AuditEventRepository(org_world)
    app.include_router(approvals.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield org_world, app.state.pending_action_repo, client


async def propose(repo, actor=MEMBER, organization=ORG, *, generic=False, call_id="call-1"):
    with acting(actor, organization):
        if generic:
            return await repo.create(action_type="other", target="draft", payload={"text": "Draft only"}, user_id=actor, organization_id=organization)
        return await repo.create(
            action_type="composio_tool_call",
            target="composio-me",
            payload={"server_name": "composio-me", "tool_name": "GMAIL_SEND_EMAIL", "arguments": {"recipient_email": "qa@example.test", "body": "Exact draft"}, "tool_call_id": call_id},
            user_id=actor,
            organization_id=organization,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("reviewer", [OWNER, ADMIN])
async def test_owner_admin_can_list_read_reject_with_real_uuid_and_audit(world, reviewer):
    sf, repo, client = world
    row = await propose(repo)
    headers = auth_headers(reviewer, ORG)
    assert isinstance(USERS[reviewer].id, UUID)
    assert (await client.get("/api/approvals", headers=headers)).json()["approvals"][0]["id"] == row["id"]
    assert (await client.get(f"/api/approvals/{row['id']}", headers=headers)).json()["payload"] == row["payload"]
    rejected = await client.post(f"/api/approvals/{row['id']}/reject", headers=headers)
    assert rejected.status_code == 200
    assert (rejected.json()["status"], rejected.json()["decided_by"]) == ("rejected", reviewer)
    assert rejected.json()["payload"] == rejected.json()["original_payload"] == row["payload"]
    assert (await client.post(f"/api/approvals/{row['id']}/reject", headers=headers)).status_code == 409
    with acting(MEMBER):
        persisted = await repo.get(row["id"])
        assert {key: persisted[key] for key in rejected.json()} == rejected.json()
        assert await repo.claim_composio_execution(row["id"]) is None
        assert (await execute_approved(persisted)).status == "failed"
    events, _ = await AuditEventRepository(sf).list(organization_id=ORG)
    decisions = [event for event in events if event["action"] == "approvals.rejected"]
    assert len(decisions) == 1
    assert decisions[0]["actor_user_id"] == reviewer and decisions[0]["target_id"] == row["id"]


@pytest.mark.asyncio
async def test_successful_reject_keeps_response_and_audit_after_post_commit_role_revocation(world):
    sf, repo, client = world
    row = await propose(repo)
    downgraded = False

    def downgrade_after_rejection_commits(session):
        nonlocal downgraded
        if downgraded:
            return
        with closing(sqlite3.connect(sf.kw["bind"].url.database)) as connection:
            committed = connection.execute("SELECT status, decided_by FROM pending_actions WHERE id = ?", (row["id"],)).fetchone()
            if committed != ("rejected", ADMIN):
                return
            connection.execute("UPDATE organization_members SET role = 'member' WHERE organization_id = ? AND user_id = ?", (ORG, ADMIN))
            connection.commit()
        downgraded = True

    event.listen(Session, "after_commit", downgrade_after_rejection_commits)
    try:
        headers = auth_headers(ADMIN, ORG)
        rejected = await client.post(f"/api/approvals/{row['id']}/reject", headers=headers)
        assert downgraded
        assert rejected.status_code == 200
        assert (rejected.json()["status"], rejected.json()["decided_by"]) == ("rejected", ADMIN)
        assert rejected.json()["payload"] == rejected.json()["original_payload"] == row["payload"]
        with acting(MEMBER):
            persisted = await repo.get(row["id"])
            assert {key: persisted[key] for key in rejected.json()} == rejected.json()
        assert (await client.post(f"/api/approvals/{row['id']}/reject", headers=headers)).status_code == 403
        assert (await client.get(f"/api/approvals/{row['id']}", headers=headers)).status_code == 404
        with acting(MEMBER):
            assert await repo.get(row["id"]) == persisted
        events, _ = await AuditEventRepository(sf).list(organization_id=ORG)
        decisions = [event for event in events if event["action"] == "approvals.rejected"]
        assert len(decisions) == 1
        assert decisions[0]["actor_user_id"] == ADMIN and decisions[0]["target_id"] == row["id"]
    finally:
        event.remove(Session, "after_commit", downgrade_after_rejection_commits)


@pytest.mark.asyncio
@pytest.mark.parametrize("reviewer", [OWNER, ADMIN])
async def test_cross_member_approve_requires_proposer_binding_and_edit_stays_hidden(world, reviewer):
    _, repo, client = world
    row = await propose(repo)
    headers = auth_headers(reviewer, ORG)
    assert (await client.post(f"/api/approvals/{row['id']}/approve", headers=headers)).status_code == (409 if reviewer == OWNER else 403)
    assert (await client.patch(f"/api/approvals/{row['id']}", json={"title": "Changed"}, headers=headers)).status_code == 404
    with acting(MEMBER):
        assert await repo.get(row["id"]) == row


@pytest.mark.asyncio
async def test_ordinary_member_has_actor_only_visibility_and_no_cross_mutations(world):
    _, repo, client = world
    foreign = await propose(repo, OWNER)
    own = await propose(repo)
    headers = auth_headers(MEMBER, ORG)
    assert [r["id"] for r in (await client.get("/api/approvals", headers=headers)).json()["approvals"]] == [own["id"]]
    assert (await client.get(f"/api/approvals/{foreign['id']}", headers=headers)).status_code == 404
    assert (await client.post(f"/api/approvals/{foreign['id']}/approve", headers=headers)).status_code == 404
    assert (await client.post(f"/api/approvals/{foreign['id']}/reject", headers=headers)).status_code == 403
    assert (await client.patch(f"/api/approvals/{foreign['id']}", json={"title": "Changed"}, headers=headers)).status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("actor,organization", [(OWNER, private_organization_id(OWNER)), (FOREIGN, FOREIGN_ORG)])
async def test_other_active_org_admin_cannot_read_or_reject(world, actor, organization):
    _, repo, client = world
    row = await propose(repo)
    headers = auth_headers(actor, organization)
    assert (await client.get("/api/approvals", headers=headers)).json()["approvals"] == []
    assert (await client.get(f"/api/approvals/{row['id']}", headers=headers)).status_code == 404
    assert (await client.post(f"/api/approvals/{row['id']}/reject", headers=headers)).status_code == 404
    assert (await client.get("/api/approvals", headers=auth_headers(FOREIGN, ORG))).status_code == 403


@pytest.mark.asyncio
async def test_existing_inbox_union_filters_sorts_dedupes_and_caps(world):
    _, repo, client = world
    hidden = await propose(repo, MEMBER, generic=True)
    with acting(OWNER):
        own_normal = await repo.create(action_type="other", target="draft", payload={"text": "Own storage"}, organization_id=ORG)
    own_composio = await propose(repo, OWNER)
    newest = await propose(repo, call_id="call-2")
    foreign = await propose(repo, FOREIGN, FOREIGN_ORG)
    headers = auth_headers(OWNER, ORG)
    all_rows = (await client.get("/api/approvals", headers=headers)).json()["approvals"]
    assert [r["id"] for r in all_rows] == [newest["id"], own_composio["id"], own_normal["id"]]
    assert (await client.get("/api/approvals?limit=2", headers=headers)).json()["approvals"] == all_rows[:2]
    for row in (hidden, foreign):
        assert (await client.get(f"/api/approvals/{row['id']}", headers=headers)).status_code == 404
        assert (await client.post(f"/api/approvals/{row['id']}/reject", headers=headers)).status_code == 404
    await client.post(f"/api/approvals/{newest['id']}/reject", headers=headers)
    assert [r["id"] for r in (await client.get("/api/approvals?status=rejected&limit=1", headers=headers)).json()["approvals"]] == [newest["id"]]
    assert newest["id"] not in [r["id"] for r in (await client.get("/api/approvals?status=pending", headers=headers)).json()["approvals"]]


@pytest.mark.asyncio
@pytest.mark.parametrize("actor,context_actor", [(MEMBER, MEMBER), (OWNER, ADMIN), (FOREIGN, FOREIGN)])
async def test_repository_oversight_denies_member_actor_mismatch_or_foreign_org(world, actor, context_actor):
    _, repo, _ = world
    row = await propose(repo)
    with acting(actor, context_actor=context_actor):
        assert await repo.list_composio_for_org() == []
        assert await repo.get_composio_for_org(row["id"]) is None
        assert await repo.reject_composio_for_org(row["id"]) is None
    with acting(MEMBER):
        assert await repo.get(row["id"]) == row


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["inactive", "member", "disabled"])
async def test_repository_oversight_rechecks_current_membership_and_user(world, change):
    sf, repo, _ = world
    row = await propose(repo)
    async with sf() as session, session.begin():
        if change == "disabled":
            await session.execute(update(UserRow).where(UserRow.id == OWNER).values(disabled_at=datetime.now(UTC)))
        else:
            await session.execute(update(OrganizationMemberRow).where(OrganizationMemberRow.user_id == OWNER, OrganizationMemberRow.organization_id == ORG).values(**({"status": "inactive"} if change == "inactive" else {"role": "member"})))
    with acting(OWNER):
        assert await repo.list_composio_for_org() == []
        assert await repo.get_composio_for_org(row["id"]) is None
        assert await repo.reject_composio_for_org(row["id"]) is None


@pytest.mark.asyncio
async def test_proposer_existing_generic_repository_scope_and_decision_unchanged(world):
    _, repo, client = world
    row = await propose(repo, OWNER)
    with acting(ADMIN):
        assert await repo.get(row["id"]) is None
        assert await repo.list() == []
        assert await repo.edit(row["id"], title="Changed") is None
        assert await repo.decide(row["id"], approve=True, decided_by=ADMIN) is None
        assert await repo.claim_composio_execution(row["id"]) is None
    with acting(OWNER):
        assert (await repo.get(row["id"]))["user_id"] == OWNER
        assert (await repo.decide(row["id"], approve=True, decided_by=OWNER))["status"] == "approved"
    assert (await client.post(f"/api/approvals/{row['id']}/reject", headers=auth_headers(ADMIN, ORG))).status_code == 409
