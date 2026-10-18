"""Canonical client admission and private lease proof over real Gateway rows."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI
from org_isolation_fixtures import ORG_A, ORG_B, ORG_S, STORAGE_S, USER_A, USER_B, acting_as, auth_headers, org_world  # noqa: F401
from sqlalchemy import func, select, update

from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.internal_auth import create_internal_auth_headers
from app.gateway.routers import fleet_work
from deerflow.persistence.clients import ClientRepository
from deerflow.persistence.clients.model import ClientRow
from deerflow.persistence.organizations.delegation import OrganizationDelegationRepository
from deerflow.persistence.organizations.model import OrganizationMemberRow
from deerflow.persistence.subagent_batches import SubagentBatchItemRow, SubagentBatchRepository, SubagentBatchRow
from deerflow.persistence.thread_meta.model import ThreadMetaRow
from deerflow.persistence.user.model import UserRow

pytestmark = pytest.mark.asyncio

CLIENT_ID = "client-one"
SOURCE_REF = f"client-operations-canonical:client/{CLIENT_ID}"


def _private_body(**overrides):
    body = {
        "thread_id": "fleet-client-thread",
        "title": "Synthetic private draft",
        "project": "outreach",
        "source_ref": SOURCE_REF,
        "client_id": CLIENT_ID,
        "lane": "haiku",
        "data_class": "private",
        "submission_key": "private-occurrence-1",
        "items": [{"key": "draft", "prompt": "Return a synthetic draft."}],
    }
    body.update(overrides)
    return body


async def _setup(session_factory):
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.include_router(fleet_work.router)
    app.state.client_repo = ClientRepository(session_factory)
    app.state.subagent_batch_repo = SubagentBatchRepository(session_factory)
    with acting_as(USER_A, ORG_A):
        await app.state.client_repo.upsert_by_registry_id(registry_id=CLIENT_ID, display_name="Synthetic Client One", status="active")
    async with session_factory() as session, session.begin():
        session.add(ThreadMetaRow(thread_id="fleet-client-thread", user_id=USER_A, organization_id=ORG_A))
        session.add(ThreadMetaRow(thread_id="fleet-other-thread", user_id=USER_B, organization_id=ORG_B))
    delegations = OrganizationDelegationRepository(session_factory)
    delegation = await delegations.grant(
        organization_id=ORG_A,
        subject_type="test_fleet_host",
        subject_id="host-one",
        owner_user_id=USER_A,
        scopes=["fleet:work"],
    )
    no_scope = await delegations.grant(
        organization_id=ORG_A,
        subject_type="test_fleet_host",
        subject_id="host-two",
        owner_user_id=USER_A,
        scopes=["threads:read"],
    )
    return app, delegation, no_scope


def _verify_path(item_id, lease_owner):
    return f"/api/fleet/work/{item_id}/client-lease?lease_owner={lease_owner}"


async def test_client_submission_requires_current_owner_and_canonical_binding(org_world):  # noqa: F811
    app, _delegation, _no_scope = await _setup(org_world)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        good = await client.post("/api/fleet/work/batches", headers=auth_headers(USER_A), json=_private_body())
        assert good.status_code == 201, good.text
        with acting_as(USER_A, ORG_A):
            await app.state.client_repo.upsert_by_registry_id(registry_id="client-two", display_name="Synthetic Client Two", status="active")
        separate_client = await client.post(
            "/api/fleet/work/batches",
            headers=auth_headers(USER_A),
            json=_private_body(client_id="client-two", source_ref="client-operations-canonical:client/client-two"),
        )
        assert separate_client.status_code == 201, separate_client.text
        assert separate_client.json()["id"] != good.json()["id"]
        for change in (
            {"client_id": "unknown-client", "source_ref": "client-operations-canonical:client/unknown-client", "submission_key": "unknown"},
            {"client_id": CLIENT_ID, "source_ref": "client-operations-canonical:client/other-client"},
            {"client_id": CLIENT_ID, "source_ref": "canonical:other"},
            {"client_id": CLIENT_ID, "lane": "spark", "data_class": "public"},
            {"client_id": CLIENT_ID, "lane": "ultrafast", "data_class": "synthetic"},
            {"client_id": None},
            {"thread_id": "foreign-or-missing-thread"},
        ):
            denied = await client.post("/api/fleet/work/batches", headers=auth_headers(USER_A), json=_private_body(**change))
            assert denied.status_code in (404, 422), (change, denied.text)
        outsider = await client.post("/api/fleet/work/batches", headers=auth_headers(USER_B), json=_private_body(submission_key="outsider"))
        assert outsider.status_code in (403, 404)
        async with org_world() as session, session.begin():
            await session.execute(update(SubagentBatchRow).where(SubagentBatchRow.id == good.json()["id"]).values(status="running"))


async def test_private_lease_verifier_is_fresh_scoped_and_leak_free(org_world):  # noqa: F811
    app, delegation, no_scope = await _setup(org_world)
    owner_headers = auth_headers(USER_A)
    host_headers = create_internal_auth_headers(owner_user_id=USER_A, delegation_id=delegation)
    no_scope_headers = create_internal_auth_headers(owner_user_id=USER_A, delegation_id=no_scope)
    repo = app.state.subagent_batch_repo
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        submitted = await client.post("/api/fleet/work/batches", headers=owner_headers, json=_private_body())
        assert submitted.status_code == 201, submitted.text
        claimed = (await repo.claim_items(now=datetime.now(UTC), lease_owner="host:claim-1", lease_seconds=60, limit=1, executor="fleet", lanes={"haiku"}))[0]
        item_id = claimed["id"]
        path = _verify_path(item_id, "host:claim-1")
        assert (await client.get(path, headers=host_headers)).status_code == 404  # leased is insufficient
        assert await repo.mark_item_running(item_id, lease_owner="host:claim-1", now=datetime.now(UTC))
        async with org_world() as session, session.begin():
            await session.execute(update(SubagentBatchItemRow).where(SubagentBatchItemRow.id == item_id).values(result="private synthetic result"))
        verified = await client.get(path, headers=host_headers)
        assert verified.status_code == 200, verified.text
        assert verified.json()["item_id"] == item_id
        assert verified.json()["owner_id"] == USER_A
        assert verified.json()["client_id"] == CLIENT_ID
        assert verified.json()["source_ref"] == SOURCE_REF
        assert verified.json()["status"] == "running"
        assert verified.json()["lease_expires_at"] > datetime.now(UTC).timestamp()
        assert set(verified.json()) == {
            "item_id",
            "lease_owner",
            "owner_id",
            "client_id",
            "source_ref",
            "status",
            "lease_expires_at",
            "executor",
            "lane",
            "data_class",
            "output_policy",
            "cancel_requested",
        }
        assert "private synthetic result" not in verified.text
        assert "Return a synthetic draft" not in verified.text
        for denied_headers in (
            {},
            owner_headers,
            no_scope_headers,
            create_internal_auth_headers(owner_user_id=USER_B, delegation_id=delegation),
        ):
            assert (await client.get(path, headers=denied_headers)).status_code in (401, 403)
        assert (await client.get(_verify_path(item_id, "host:forged"), headers=host_headers)).status_code == 404
        async with org_world() as session, session.begin():
            await session.execute(update(SubagentBatchItemRow).where(SubagentBatchItemRow.id == item_id).values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=1)))
        assert (await client.get(path, headers=host_headers)).status_code == 404
        async with org_world() as session, session.begin():
            await session.execute(update(SubagentBatchItemRow).where(SubagentBatchItemRow.id == item_id).values(lease_owner="host:reclaimed", lease_expires_at=datetime.now(UTC) + timedelta(seconds=60)))
        assert (await client.get(path, headers=host_headers)).status_code == 404
        assert (await client.get(_verify_path(item_id, "host:reclaimed"), headers=host_headers)).status_code == 200
        async with org_world() as session, session.begin():
            await session.execute(update(SubagentBatchItemRow).where(SubagentBatchItemRow.id == item_id).values(cancel_requested_at=datetime.now(UTC)))
        assert (await client.get(_verify_path(item_id, "host:reclaimed"), headers=host_headers)).status_code == 404


async def test_durable_client_policy_and_batch_cancel_rechecked(org_world):  # noqa: F811
    app, delegation, _no_scope = await _setup(org_world)
    host_headers = create_internal_auth_headers(owner_user_id=USER_A, delegation_id=delegation)
    repo = app.state.subagent_batch_repo
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/api/fleet/work/batches", headers=auth_headers(USER_A), json=_private_body())
        assert created.status_code == 201
        item = (await repo.claim_items(now=datetime.now(UTC), lease_owner="host:policy", lease_seconds=60, limit=1, executor="fleet", lanes={"haiku"}))[0]
        assert await repo.mark_item_running(item["id"], lease_owner="host:policy", now=datetime.now(UTC))
        path = _verify_path(item["id"], "host:policy")
        assert (await client.get(path, headers=host_headers)).status_code == 200
        async with org_world() as session, session.begin():
            batch = await session.get(SubagentBatchRow, created.json()["id"])
            batch.execution_spec = {**batch.execution_spec, "source_ref": "client-operations-canonical:client/forged"}
        assert (await client.get(path, headers=host_headers)).status_code == 404
        async with org_world() as session, session.begin():
            batch = await session.get(SubagentBatchRow, created.json()["id"])
            batch.execution_spec = {**batch.execution_spec, "source_ref": SOURCE_REF}
            await session.execute(update(ClientRow).where(ClientRow.registry_id == CLIENT_ID).values(status="inactive"))
        assert (await client.get(path, headers=host_headers)).status_code == 404
        async with org_world() as session, session.begin():
            await session.execute(update(ClientRow).where(ClientRow.registry_id == CLIENT_ID).values(status="active"))
        assert (await client.get(path, headers=host_headers)).status_code == 200
        cancelled = await client.post(f"/api/fleet/work/projects/outreach/batches/{item['batch_id']}/cancel", headers=auth_headers(USER_A))
        assert cancelled.status_code == 200
        assert (await client.get(path, headers=host_headers)).status_code == 404


async def test_ultrafast_submit_is_public_bounded_and_single_attempt(org_world):  # noqa: F811
    app, delegation, _no_scope = await _setup(org_world)
    body = _private_body(client_id=None, source_ref="canonical:synthetic-card", lane="ultrafast", data_class="synthetic")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        for change in (
            {"data_class": "private"},
            {"max_attempts": 2},
            {"max_tokens": 4097},
            {"items": [{"key": "draft", "prompt": "🔥" * 4001}]},
        ):
            denied = await client.post("/api/fleet/work/batches", headers=auth_headers(USER_A), json={**body, **change})
            assert denied.status_code == 422, (change.keys(), denied.text)
        created = await client.post("/api/fleet/work/batches", headers=auth_headers(USER_A), json=body)
        assert created.status_code == 201, created.text
        claimed = await app.state.subagent_batch_repo.claim_items(now=datetime.now(UTC), lease_owner="host:ultrafast", lease_seconds=60, limit=1, executor="fleet", lanes={"ultrafast"})
        assert len(claimed) == 1
        assert claimed[0]["batch"]["execution_spec"]["max_tokens"] == 4096
        assert await app.state.subagent_batch_repo.mark_item_running(claimed[0]["id"], lease_owner="host:ultrafast", now=datetime.now(UTC))
        assert not await app.state.subagent_batch_repo.requeue_item_after_admission_failure(claimed[0]["id"], lease_owner="host:ultrafast", error="uncertain paid outcome", now=datetime.now(UTC))
        release = await client.post(
            f"/api/fleet/work/{claimed[0]['id']}/release",
            headers=create_internal_auth_headers(owner_user_id=USER_A, delegation_id=delegation),
            json={"lease_owner": "host:ultrafast", "error": "uncertain paid outcome"},
        )
        assert release.status_code == 409
        running = (await app.state.subagent_batch_repo.list_items(created.json()["id"], user_id=USER_A))[0]
        assert (running["attempt"], running["status"]) == (1, "running")
        stored = await app.state.subagent_batch_repo.get_batch(created.json()["id"], user_id=USER_A)
        assert stored["max_attempts"] == 1
        with acting_as(USER_A, ORG_A):
            await app.state.subagent_batch_repo.create_batch(
                batch_id="legacy-ultrafast-bad-retry",
                user_id=USER_A,
                thread_id="fleet-client-thread",
                run_id=None,
                tool_call_id=None,
                submission_key="legacy-ultrafast-retry",
                title="Old synthetic paid row",
                subagent_type="fleet-ultrafast@backend",
                items=[{"key": "draft", "prompt": "Old synthetic prompt"}],
                max_live_items=1,
                max_running_items=1,
                max_attempts=2,
                execution_spec={"executor": "fleet", "lane": "ultrafast", "data_class": "synthetic", "project": "backend", "output_policy": "draft-only"},
            )
        assert (
            await app.state.subagent_batch_repo.claim_items(
                now=datetime.now(UTC),
                lease_owner="host:next",
                lease_seconds=60,
                limit=10,
                executor="fleet",
                lanes={"ultrafast"},
                owner_id=USER_A,
                organization_id=ORG_A,
            )
            == []
        )


async def test_claim_is_internal_and_storage_owner_scoped(org_world):  # noqa: F811
    app, delegation_a, no_scope = await _setup(org_world)
    delegation_b = await OrganizationDelegationRepository(org_world).grant(
        organization_id=ORG_B,
        subject_type="test_fleet_host",
        subject_id="host-b",
        owner_user_id=USER_B,
        scopes=["fleet:work"],
    )
    public_body = {
        "title": "Synthetic public job",
        "project": "philadelphia",
        "source_ref": "canonical:synthetic-public-card",
        "lane": "spark",
        "data_class": "public",
        "submission_key": "public-occurrence",
        "items": [{"key": "draft", "prompt": "Synthetic prompt owned by A"}],
    }
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        async with org_world() as session:
            before = await session.scalar(select(func.count()).select_from(SubagentBatchRow))
        for invalid_thread in ("missing-fleet-thread", "fleet-other-thread"):
            refused = await client.post(
                "/api/fleet/work/batches",
                headers=auth_headers(USER_A),
                json={**public_body, "thread_id": invalid_thread},
            )
            assert refused.status_code == 404, (invalid_thread, refused.text)
        async with org_world() as session:
            assert await session.scalar(select(func.count()).select_from(SubagentBatchRow)) == before
        a = await client.post("/api/fleet/work/batches", headers=auth_headers(USER_A), json={**public_body, "thread_id": "fleet-client-thread"})
        b = await client.post(
            "/api/fleet/work/batches",
            headers=auth_headers(USER_B),
            json={**public_body, "thread_id": "fleet-other-thread", "items": [{"key": "draft", "prompt": "Synthetic prompt owned by B"}]},
        )
        assert (a.status_code, b.status_code) == (201, 201)
        claim_path = "/api/fleet/work/claim"
        claim_body = {"lease_owner": "host:claim-a", "lanes": ["spark"], "limit": 10}
        assert (await client.post(claim_path, headers=auth_headers(USER_A), json=claim_body)).status_code == 403
        assert (await client.post(claim_path, headers=create_internal_auth_headers(owner_user_id=USER_A, delegation_id=no_scope), json=claim_body)).status_code == 403
        claim_a = await client.post(claim_path, headers=create_internal_auth_headers(owner_user_id=USER_A, delegation_id=delegation_a), json=claim_body)
        assert claim_a.status_code == 200, claim_a.text
        assert [item["batch_id"] for item in claim_a.json()["items"]] == [a.json()["id"]]
        assert "Synthetic prompt owned by B" not in claim_a.text
        claim_b = await client.post(
            claim_path,
            headers=create_internal_auth_headers(owner_user_id=USER_B, delegation_id=delegation_b),
            json={**claim_body, "lease_owner": "host:claim-b"},
        )
        assert claim_b.status_code == 200, claim_b.text
        assert [item["batch_id"] for item in claim_b.json()["items"]] == [b.json()["id"]]
        assert "Synthetic prompt owned by A" not in claim_b.text

        a_item = claim_a.json()["items"][0]["id"]
        host_b = create_internal_auth_headers(owner_user_id=USER_B, delegation_id=delegation_b)
        for suffix, payload in (
            ("renew", {"lease_owner": "host:claim-a"}),
            ("running", {"lease_owner": "host:claim-a"}),
            ("finalize", {"lease_owner": "host:claim-a", "succeeded": True, "result": "forged"}),
            ("release", {"lease_owner": "host:claim-a"}),
        ):
            denied = await client.post(f"/api/fleet/work/{a_item}/{suffix}", headers=host_b, json=payload)
            assert denied.status_code == 404, (suffix, denied.text)
        still_leased = (await app.state.subagent_batch_repo.list_items(a.json()["id"], user_id=USER_A))[0]
        assert (still_leased["status"], still_leased["attempt"]) == ("leased", 1)
        host_a = create_internal_auth_headers(owner_user_id=USER_A, delegation_id=delegation_a)
        assert (await client.post(f"/api/fleet/work/{a_item}/running", headers=host_a, json={"lease_owner": "host:claim-a"})).status_code == 200
        assert (await client.post(f"/api/fleet/work/{a_item}/renew", headers=host_a, json={"lease_owner": "host:claim-a"})).json()["valid"]

    # Internal fleet filters must not change the native service's unscoped
    # executor partition: it can still claim native work from its own queue.
    repo = app.state.subagent_batch_repo
    with acting_as(USER_A, ORG_A):
        await repo.create_batch(
            batch_id="native-batch-a",
            user_id=USER_A,
            thread_id="fleet-client-thread",
            run_id=None,
            tool_call_id=None,
            submission_key="native-occurrence",
            title="Native synthetic",
            subagent_type="test-native",
            items=[{"key": "one", "prompt": "Native synthetic prompt"}],
            max_live_items=1,
            max_running_items=1,
            max_attempts=1,
            execution_spec={"executor": "native"},
        )
    native = await repo.claim_items(now=datetime.now(UTC), lease_owner="native:claim", lease_seconds=60, limit=1)
    assert [item["batch_id"] for item in native] == ["native-batch-a"]


async def test_shared_member_assignment_revocation_denies_next_client_read(org_world):  # noqa: F811
    member_id = "fleet-member"
    registry_id = "shared-client"
    now = datetime.now(UTC)
    async with org_world() as session, session.begin():
        session.add(UserRow(id=member_id, email="fleet-member@example.com", password_hash=None, system_role="user", needs_setup=False, token_version=0, created_at=now))
        session.add(OrganizationMemberRow(organization_id=ORG_S, user_id=member_id, role="member", status="active", created_at=now, updated_at=now))
        session.add(ThreadMetaRow(thread_id="shared-fleet-thread", user_id=STORAGE_S, organization_id=ORG_S))
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.include_router(fleet_work.router)
    app.state.client_repo = ClientRepository(org_world)
    app.state.subagent_batch_repo = SubagentBatchRepository(org_world)
    with acting_as(USER_A, ORG_S):
        _outcome, imported = await app.state.client_repo.upsert_by_registry_id(registry_id=registry_id, display_name="Synthetic Shared Client", status="active")
        assert imported is not None
        await app.state.client_repo.add_assignment(imported["id"], member_id, "contributor")
    delegation = await OrganizationDelegationRepository(org_world).grant(
        organization_id=ORG_S,
        subject_type="test_fleet_host",
        subject_id="shared-host",
        owner_user_id=member_id,
        scopes=["fleet:work"],
    )
    body = _private_body(
        thread_id="shared-fleet-thread",
        client_id=registry_id,
        source_ref=f"client-operations-canonical:client/{registry_id}",
        submission_key="shared-occurrence",
    )
    member_headers = auth_headers(member_id, ORG_S)
    host_headers = create_internal_auth_headers(owner_user_id=member_id, delegation_id=delegation)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/api/fleet/work/batches", headers=member_headers, json=body)
        assert created.status_code == 201, created.text
        claimed = (
            await app.state.subagent_batch_repo.claim_items(
                now=datetime.now(UTC),
                lease_owner="host:shared-claim",
                lease_seconds=60,
                limit=1,
                executor="fleet",
                lanes={"haiku"},
                owner_id=STORAGE_S,
                organization_id=ORG_S,
            )
        )[0]
        assert await app.state.subagent_batch_repo.mark_item_running(claimed["id"], lease_owner="host:shared-claim", now=datetime.now(UTC))
        path = _verify_path(claimed["id"], "host:shared-claim")
        assert (await client.get(path, headers=host_headers)).status_code == 200
        with acting_as(USER_A, ORG_S):
            assert await app.state.client_repo.remove_assignment(imported["id"], member_id)
        assert (await client.get(path, headers=host_headers)).status_code == 404
        denied = await client.post("/api/fleet/work/batches", headers=member_headers, json={**body, "submission_key": "shared-next"})
        assert denied.status_code == 404
