"""Offline HTTP acceptance with verified auth contexts and real SQLite.

Token verification/CSRF remain separate middleware deployment gates.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI, Request
from pydantic import ValidationError

from app.gateway.authz import AuthContext
from app.gateway.routers import fleet_work
from deerflow.config.database_config import DatabaseConfig
from deerflow.persistence.engine import get_session_factory, init_engine_from_config
from deerflow.persistence.subagent_batches import SubagentBatchRepository


async def _client(tmp_path, monkeypatch):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    factory = get_session_factory()
    assert factory is not None
    repo = SubagentBatchRepository(factory)
    # This suite isolates project binding/idempotency with a synthetic auth
    # context. Real owned-thread admission is exercised behind AuthMiddleware
    # in test_fleet_client_lease.py.
    monkeypatch.setattr(repo, "owns_thread_for_fleet_project", AsyncMock(return_value=True))
    app = FastAPI()
    app.state.subagent_batch_repo = repo

    @app.middleware("http")
    async def verified_auth(request: Request, call_next):
        owner = request.headers.get("x-test-owner")
        user = SimpleNamespace(id=owner) if owner else None
        permissions = ["fleet:work"] if request.headers.get("x-test-scope") == "fleet" else []
        request.state.auth = AuthContext(user=user, permissions=permissions)
        request.state.test_owner = owner
        return await call_next(request)

    async def owner(request):
        return request.state.test_owner

    monkeypatch.setattr(fleet_work, "get_current_user", owner)
    app.include_router(fleet_work.router)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test"), repo, factory


def _body(project):
    return {
        "thread_id": "synthetic-thread",
        "title": "Synthetic draft job",
        "project": project,
        "source_ref": "canonical:synthetic-card-1",
        "lane": "haiku",
        "data_class": "synthetic",
        "submission_key": "occurrence-1",
        "items": [{"key": "draft", "prompt": "Return a synthetic draft"}],
    }


@pytest.mark.asyncio
async def test_four_projects_persist_and_cancel_fences_running_job(tmp_path, monkeypatch):
    client, repo, factory = await _client(tmp_path, monkeypatch)
    headers = {"x-test-owner": "owner-1", "x-test-scope": "fleet"}
    async with client:
        catalog = await client.get("/api/fleet/work/projects", headers=headers)
        assert catalog.status_code == 200
        assert [p["id"] for p in catalog.json()["projects"]] == list(fleet_work.PROJECTS)
        assert all(not p["schedule_active"] for p in catalog.json()["projects"])
        batches = {}
        for project in fleet_work.PROJECTS:
            response = await client.post("/api/fleet/work/batches", headers=headers, json=_body(project))
            assert response.status_code == 201, response.text
            batches[project] = response.json()["id"]
            replay = await client.post("/api/fleet/work/batches", headers=headers, json=_body(project))
            assert replay.json()["id"] == batches[project]
        assert len(set(batches.values())) == 4
        reopened = SubagentBatchRepository(factory)
        for project, batch_id in batches.items():
            stored = await reopened.get_batch(batch_id, user_id="owner-1")
            assert stored["subagent_type"] == f"fleet-haiku@{project}"
        item = (await repo.claim_items(now=datetime.now(UTC), lease_owner="host:unique-claim", lease_seconds=60, limit=1, executor="fleet", lanes={"haiku"}))[0]
        project = item["batch"]["execution_spec"]["project"]
        assert item["batch"]["execution_spec"]["output_policy"] == "draft-only"
        assert await repo.mark_item_running(item["id"], lease_owner="host:unique-claim", now=datetime.now(UTC))
        cancelled = await client.post(f"/api/fleet/work/projects/{project}/batches/{item['batch_id']}/cancel", headers=headers)
        assert cancelled.status_code == 200
        assert cancelled.json()["batch"]["status"] == "cancelled"
        assert not (await repo.renew_item_lease(item["id"], lease_owner="host:unique-claim", lease_seconds=60, now=datetime.now(UTC)))["valid"]
        assert await repo.claim_items(now=datetime.now(UTC), lease_owner="other", lease_seconds=60, limit=10, executor="fleet", lanes={"haiku"})
        assert (await reopened.get_batch(item["batch_id"], user_id="owner-1"))["status"] == "cancelled"


@pytest.mark.asyncio
async def test_http_permission_owner_project_and_private_spark_boundaries(tmp_path, monkeypatch):
    client, repo, _factory = await _client(tmp_path, monkeypatch)
    headers = {"x-test-owner": "owner-1", "x-test-scope": "fleet"}
    async with client:
        assert (await client.get("/api/fleet/work/projects")).status_code == 401
        assert (await client.get("/api/fleet/work/projects", headers={"x-test-owner": "owner-1"})).status_code == 403
        created = await client.post("/api/fleet/work/batches", headers=headers, json=_body("outreach"))
        batch_id = created.json()["id"]
        path = f"/api/fleet/work/projects/outreach/batches/{batch_id}"
        assert (await client.get(path, headers=headers)).status_code == 200
        other = {**headers, "x-test-owner": "owner-2"}
        assert (await client.get(path, headers=other)).status_code == 404
        assert (await client.post(path + "/cancel", headers=other)).status_code == 404
        assert (await client.post(path.replace("/outreach/", "/backend/") + "/cancel", headers=headers)).status_code == 404
        body = {**_body("outreach"), "lane": "spark", "data_class": "private"}
        assert (await client.post("/api/fleet/work/batches", headers=headers, json=body)).status_code == 422
        assert (await repo.get_batch(batch_id, user_id="owner-1"))["status"] == "queued"


def test_project_binding_requires_safe_reference_and_known_project():
    for change in (
        {"source_ref": None},
        {"project": "invented"},
        {"source_ref": "Bearer secret value"},
        {"source_ref": "https://user:password@example.com"},
        {"source_ref": "canonical:../other-client"},
        {"source_ref": "canonical://other-client"},
    ):
        with pytest.raises(ValidationError):
            fleet_work.FleetBatchSubmit(**{**_body("backend"), **change})
