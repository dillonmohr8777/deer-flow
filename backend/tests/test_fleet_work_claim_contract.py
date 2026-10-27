"""Runner contract for POST /api/fleet/work/claim (synthetic data only).

The Mac fleet runner (``fleet/runner/runner.py``) polls this exact path with an
internal token plus delegation id. Before this route was mounted the Gateway
answered 404 on every poll, so these tests pin: the path exists end to end
(no 404), unauthenticated callers are refused, a non-delegated caller gets 403,
an empty queue is a normal 200 with no items, and a queued item is leased.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from org_isolation_fixtures import ORG_A, USER_A, acting_as, auth_headers, org_world  # noqa: F401

from app.gateway.app import create_app
from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.internal_auth import create_internal_auth_headers
from app.gateway.routers import fleet_work
from deerflow.config.subagent_batches_config import SubagentBatchesConfig
from deerflow.persistence.clients import ClientRepository
from deerflow.persistence.organizations.delegation import OrganizationDelegationRepository
from deerflow.persistence.subagent_batches import SubagentBatchRepository, SubagentBatchRow
from deerflow.persistence.thread_meta.model import ThreadMetaRow

RUNNER_BODY = {"lease_owner": "mac-mini:w-haiku-01", "lanes": ["haiku"], "limit": 1}


@pytest.mark.asyncio
async def test_workspace_survives_http_submission_storage_and_selected_claim(org_world):  # noqa: F811
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.include_router(fleet_work.router)
    app.state.subagent_batch_repo = SubagentBatchRepository(org_world)
    app.state.client_repo = ClientRepository(org_world)
    with acting_as(USER_A, ORG_A):
        await app.state.client_repo.upsert_by_registry_id(registry_id="synthetic-client", display_name="Synthetic Client", status="active")
    async with org_world() as session, session.begin():
        session.add(ThreadMetaRow(thread_id="synthetic-workspace-thread", user_id=USER_A, organization_id=ORG_A))
    delegation = await OrganizationDelegationRepository(org_world).grant(organization_id=ORG_A, subject_type="test_fleet_host", subject_id="synthetic-linux", owner_user_id=USER_A, scopes=["fleet:work"])
    workspace = {"environment_id": "synthetic-linux", "command": ["printf", "synthetic"], "client_path": "/clients/synthetic-client"}
    body = {
        "thread_id": "synthetic-workspace-thread",
        "title": "Synthetic workspace draft",
        "project": "backend",
        "source_ref": "client-operations-canonical:client/synthetic-client",
        "client_id": "synthetic-client",
        "lane": "haiku",
        "data_class": "private",
        "max_running_items": 3,
        "workspace": workspace,
        "items": [{"key": "one", "prompt": "Return a synthetic draft"}],
    }
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        older = await client.post("/api/fleet/work/batches", headers=auth_headers(USER_A), json={**body, "submission_key": "older"})
        selected = await client.post("/api/fleet/work/batches", headers=auth_headers(USER_A), json={**body, "submission_key": "selected"})
        assert older.status_code == selected.status_code == 201, (older.text, selected.text)
        selected_id = selected.json()["id"]
        expected_workspace = {**workspace, "timeout_seconds": 300}
        async with org_world() as session:
            stored = await session.get(SubagentBatchRow, selected_id)
            assert stored.execution_spec["workspace"] == expected_workspace
            assert stored.max_running_items == 3
        # A reconstructed repository must claim the persisted payload, not a cached submit body.
        app.state.subagent_batch_repo = SubagentBatchRepository(org_world)
        claimed = await client.post(
            "/api/fleet/work/claim",
            headers=create_internal_auth_headers(owner_user_id=USER_A, delegation_id=delegation),
            json={**RUNNER_BODY, "batch_id": selected_id},
        )
        assert claimed.status_code == 200, claimed.text
        item = claimed.json()["items"][0]
        assert item["batch_id"] == selected_id
        assert item["workspace"] == expected_workspace
        assert (item["client_id"], item["source_ref"], item["output_policy"]) == ("synthetic-client", body["source_ref"], "draft-only")
        assert item["lease_expires_at"]
        older_items = await app.state.subagent_batch_repo.list_items(older.json()["id"], user_id=USER_A)
        assert len(older_items) == 1
        assert older_items[0]["status"] in {"pending", "queued"}


def _request(repo, *, internal: bool = True, organization_id: str | None = "synthetic-org"):
    user = SimpleNamespace(id="owner-1", system_role="internal" if internal else "user")
    state = SimpleNamespace(user=user, organization_id=organization_id)
    if internal:
        state.delegation_id = "synthetic-delegation"
        state.storage_user_id = "owner-1"
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(subagent_batch_repo=repo, subagent_batches_config=SubagentBatchesConfig(lease_seconds=120))),
        state=state,
    )


def _item():
    return {
        "id": "item-synthetic-1",
        "batch_id": "batch-synthetic-1",
        "item_key": "k-1",
        "attempt": 1,
        "prompt": "Synthetic prompt",
        "acceptance_criteria": None,
        "batch": {"id": "batch-synthetic-1", "max_attempts": 2, "execution_spec": {"executor": "fleet", "lane": "haiku", "data_class": "synthetic", "effort": "high", "max_tokens": 2000}},
    }


def test_claim_path_is_mounted_and_unauthenticated_poll_is_refused_not_404() -> None:
    app = create_app()
    routes = {(route.path, tuple(sorted(getattr(route, "methods", ()) or ()))) for route in app.routes}
    assert ("/api/fleet/work/claim", ("POST",)) in routes

    # No context manager: the lifespan (DB, channels) is not needed to prove routing.
    client = TestClient(app, raise_server_exceptions=False)
    response = client.post("/api/fleet/work/claim", json=RUNNER_BODY)
    assert response.status_code != 404
    assert response.status_code in {401, 403}


@pytest.mark.asyncio
async def test_claim_returns_leased_item_for_runner_body() -> None:
    repo = SimpleNamespace(claim_items=AsyncMock(return_value=[_item()]))
    body = fleet_work.ClaimRequest(**RUNNER_BODY)

    response = await fleet_work.claim_work.__wrapped__(request=_request(repo), body=body)

    kwargs = repo.claim_items.await_args.kwargs
    assert kwargs["executor"] == "fleet"
    assert kwargs["lanes"] == {"haiku"}
    assert kwargs["owner_id"] == "owner-1"
    assert kwargs["organization_id"] == "synthetic-org"
    assert response["lease_seconds"] == 120
    assert [item["id"] for item in response["items"]] == ["item-synthetic-1"]
    assert response["items"][0]["lease_expires_at"]


@pytest.mark.asyncio
async def test_claim_passes_runner_batch_selector_to_repo() -> None:
    repo = SimpleNamespace(claim_items=AsyncMock(return_value=[]))

    await fleet_work.claim_work.__wrapped__(request=_request(repo), body=fleet_work.ClaimRequest(**RUNNER_BODY, batch_id="batch-synthetic-1"))
    await fleet_work.claim_work.__wrapped__(request=_request(repo), body=fleet_work.ClaimRequest(**RUNNER_BODY))

    assert [c.kwargs["batch_id"] for c in repo.claim_items.await_args_list] == ["batch-synthetic-1", None]


@pytest.mark.asyncio
async def test_claim_with_empty_queue_is_ok_and_empty() -> None:
    repo = SimpleNamespace(claim_items=AsyncMock(return_value=[]))

    response = await fleet_work.claim_work.__wrapped__(request=_request(repo), body=fleet_work.ClaimRequest(**RUNNER_BODY))

    assert response == {"lease_seconds": 120, "items": []}


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs", [{"internal": False}, {"organization_id": None}])
async def test_claim_without_internal_delegation_is_forbidden_and_claims_nothing(kwargs) -> None:
    repo = SimpleNamespace(claim_items=AsyncMock(return_value=[_item()]))

    with pytest.raises(HTTPException) as exc:
        await fleet_work.claim_work.__wrapped__(request=_request(repo, **kwargs), body=fleet_work.ClaimRequest(**RUNNER_BODY))

    assert exc.value.status_code == 403
    repo.claim_items.assert_not_awaited()


@pytest.mark.parametrize(
    "body",
    [
        {"lease_owner": "", "lanes": ["haiku"]},
        {"lease_owner": "w", "lanes": []},
        {"lease_owner": "w", "lanes": ["not-a-lane"]},
        {"lease_owner": "w", "lanes": ["haiku"], "limit": 0},
    ],
)
def test_claim_body_validation_rejects_malformed_runner_requests(body) -> None:
    with pytest.raises(ValueError):
        fleet_work.ClaimRequest(**body)


@pytest.mark.parametrize("delegation_state", ["valid", "missing", "wrong-scope"])
def test_runner_poll_through_real_auth_middleware(monkeypatch, delegation_state) -> None:
    """Same headers the runner sends; prod returned 404 here because the router was absent."""
    from org_isolation_fixtures import fake_delegation

    from app.gateway.auth_middleware import AuthMiddleware
    from app.gateway.internal_auth import create_internal_auth_headers

    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "0")
    monkeypatch.setenv("DEER_FLOW_INTERNAL_AUTH_TOKEN", "synthetic-internal-token")
    scopes = frozenset({"fleet:work"} if delegation_state != "wrong-scope" else {"threads:read"})
    delegation = fake_delegation("owner-1", subject_type="fleet_host", subject_id="mac-mini", scopes=scopes)
    monkeypatch.setattr("app.gateway.auth_middleware._resolve_internal_delegation", AsyncMock(return_value=None if delegation_state == "missing" else delegation))
    monkeypatch.setattr("app.gateway.auth_middleware.resolve_route_permissions", AsyncMock(return_value=["fleet:work", "threads:read"]))
    repo = SimpleNamespace(claim_items=AsyncMock(return_value=[]))
    app = FastAPI()
    app.state.subagent_batch_repo = repo
    app.add_middleware(AuthMiddleware)
    app.include_router(fleet_work.router)

    with TestClient(app) as client:
        response = client.post("/api/fleet/work/claim", headers=create_internal_auth_headers(delegation_id=delegation.id), json=RUNNER_BODY)
        unmounted = client.post("/api/fleet/work-missing/claim", headers=create_internal_auth_headers(delegation_id=delegation.id), json=RUNNER_BODY)

    if delegation_state == "valid":
        assert response.status_code == 200
        assert response.json()["items"] == []
        assert repo.claim_items.await_args.kwargs["executor"] == "fleet"
        # Control: an authenticated poll to a path with no router is the prod symptom.
        assert unmounted.status_code == 404
    else:
        assert response.status_code == 403
        repo.claim_items.assert_not_awaited()


@pytest.mark.parametrize("raw", ["not json", '{"lanes": ["haiku"]}', '{"lease_owner": "w", "lanes": "haiku"}', '{"lease_owner": "w", "lanes": ["nope"]}'])
def test_malformed_claim_body_over_http_is_422_and_claims_nothing(monkeypatch, raw) -> None:
    from org_isolation_fixtures import fake_delegation

    from app.gateway.auth_middleware import AuthMiddleware
    from app.gateway.internal_auth import create_internal_auth_headers

    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "0")
    monkeypatch.setenv("DEER_FLOW_INTERNAL_AUTH_TOKEN", "synthetic-internal-token")
    delegation = fake_delegation("owner-1", subject_type="fleet_host", subject_id="mac-mini", scopes=frozenset({"fleet:work"}))
    monkeypatch.setattr("app.gateway.auth_middleware._resolve_internal_delegation", AsyncMock(return_value=delegation))
    monkeypatch.setattr("app.gateway.auth_middleware.resolve_route_permissions", AsyncMock(return_value=["fleet:work"]))
    repo = SimpleNamespace(claim_items=AsyncMock(return_value=[]))
    app = FastAPI()
    app.state.subagent_batch_repo = repo
    app.add_middleware(AuthMiddleware)
    app.include_router(fleet_work.router)

    with TestClient(app) as client:
        response = client.post(
            "/api/fleet/work/claim",
            headers={**create_internal_auth_headers(delegation_id=delegation.id), "Content-Type": "application/json"},
            content=raw,
        )

    assert response.status_code == 422
    repo.claim_items.assert_not_awaited()
