"""Client read access through real middleware, routers and tenant-scoped storage."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from org_isolation_fixtures import ORG_S, USER_A, USER_B, auth_headers, org_world  # noqa: F401
from test_org_isolation_a_projects import _build_app, _client, _create_project, _upload_document


def _client_role(monkeypatch):
    async def user(request):
        actor = request.cookies["access_token"]
        return SimpleNamespace(id=actor, system_role="client" if actor == USER_A else "user", email="customer@example.test")

    monkeypatch.setattr("app.gateway.deps.get_current_user_from_request", user)


@pytest.mark.asyncio
async def test_client_staff_project_routes_stay_closed_even_with_broad_test_permissions(org_world, monkeypatch):  # noqa: F811
    app = _build_app(org_world)
    async with _client(app) as client:
        own = await _create_project(client, auth_headers(USER_A), "Customer reference")
        foreign = await _create_project(client, auth_headers(USER_B), "Other workspace")
        doc = await _upload_document(client, own["id"], auth_headers(USER_A), "reference.txt", b"Synthetic reference")
        _client_role(monkeypatch)
        listing = await client.get("/api/projects", headers=auth_headers(USER_A))
        assert listing.status_code == 403
        assert (await client.get(f"/api/projects/{own['id']}", headers=auth_headers(USER_A))).status_code == 403
        documents = await client.get(f"/api/projects/{own['id']}/documents", headers=auth_headers(USER_A))
        assert documents.status_code == 403
        content = await client.get(f"/api/projects/{own['id']}/documents/{doc['id']}/content", headers=auth_headers(USER_A))
        assert content.status_code == 403
        for suffix in ("", "/documents", f"/documents/{doc['id']}/content"):
            assert (await client.get(f"/api/projects/{foreign['id']}{suffix}", headers=auth_headers(USER_A))).status_code == 403
        assert (await client.get(f"/api/projects/{own['id']}/documents/not-owned/content", headers=auth_headers(USER_A))).status_code == 403
        assert (await client.get("/api/projects", headers=auth_headers(USER_B, ORG_S))).status_code == 403
        assert (await client.get("/api/projects")).status_code == 401
        assert (await client.post("/api/projects", json={"name": "Forbidden"}, headers=auth_headers(USER_A))).status_code == 403
        assert (await client.get(f"/api/projects/{own['id']}/threads", headers=auth_headers(USER_A))).status_code == 403


@pytest.mark.asyncio
async def test_client_reads_only_own_schedule_without_execution_or_history(schedules_world, monkeypatch):  # noqa: F811
    from test_org_isolation_c_schedules import _create

    world = schedules_world
    own = await _create(world, USER_A)
    foreign = await _create(world, USER_B)
    _client_role(monkeypatch)
    listing = await world.client.get("/api/scheduled-tasks", headers=auth_headers(USER_A))
    assert listing.status_code == 200
    assert [task["id"] for task in listing.json()] == [own["id"]]
    status_fields = {"id", "title", "status", "next_run_at", "last_run_at", "timezone"}
    assert set(listing.json()[0]) == status_fields
    detail = await world.client.get(f"/api/scheduled-tasks/{own['id']}", headers=auth_headers(USER_A))
    assert detail.status_code == 200
    assert set(detail.json()) == status_fields
    assert detail.json() == listing.json()[0]
    # Staff retain complete records for their existing management interface.
    staff_list = await world.client.get("/api/scheduled-tasks", headers=auth_headers(USER_B))
    staff_detail = await world.client.get(f"/api/scheduled-tasks/{foreign['id']}", headers=auth_headers(USER_B))
    assert staff_list.status_code == staff_detail.status_code == 200
    assert staff_list.json()[0]["prompt"] == foreign["prompt"]
    for field in ("prompt", "assistant_id", "thread_id", "schedule_spec", "last_run_id", "last_thread_id", "last_error"):
        assert field in staff_detail.json()

    assert (await world.client.get(f"/api/scheduled-tasks/{foreign['id']}", headers=auth_headers(USER_A))).status_code == 404
    assert (await world.client.get("/api/scheduled-tasks", headers=auth_headers(USER_B, ORG_S))).status_code == 403
    assert (await world.client.get("/api/scheduled-tasks")).status_code == 401
    for method, suffix in [("POST", "/trigger"), ("POST", "/resume"), ("POST", "/pause"), ("PATCH", ""), ("DELETE", ""), ("GET", "/runs")]:
        assert (await world.client.request(method, f"/api/scheduled-tasks/{own['id']}{suffix}", headers=auth_headers(USER_A))).status_code == 403
    assert (await world.client.post("/api/scheduled-tasks", json={}, headers=auth_headers(USER_A))).status_code == 403
    assert world.launches == []
    # No scheduler/repository installed remains unavailable, never auto-enabled.
    world.app.state.scheduled_task_repo = None
    assert (await world.client.get("/api/scheduled-tasks", headers=auth_headers(USER_A))).status_code == 503


from test_org_isolation_c_schedules import world as schedules_world  # noqa: E402,F401


@pytest.mark.asyncio
async def test_existing_shared_client_membership_keeps_workspace_and_permission_checks(schedules_world, monkeypatch):  # noqa: F811
    from sqlalchemy import update
    from test_org_isolation_c_schedules import _create

    from app.gateway.routers import projects
    from deerflow.persistence.organizations.model import OrganizationMemberRow
    from deerflow.persistence.projects import ProjectRepository

    world = schedules_world
    world.app.include_router(projects.router)
    world.app.state.project_repo = ProjectRepository(world.sf)
    project = await _create_project(world.client, auth_headers(USER_A, ORG_S), "Shared reference")
    task = await _create(world, USER_A, ORG_S)
    async with world.sf() as session, session.begin():
        await session.execute(update(OrganizationMemberRow).where(OrganizationMemberRow.user_id == USER_A, OrganizationMemberRow.organization_id == ORG_S).values(role="client"))
    _client_role(monkeypatch)
    headers = auth_headers(USER_A, ORG_S)
    assert (await world.client.get(f"/api/projects/{project['id']}", headers=headers)).status_code == 403
    assert (await world.client.get(f"/api/scheduled-tasks/{task['id']}", headers=headers)).status_code == 200
    # The same shared data is invisible after selecting the caller's private workspace.
    assert (await world.client.get(f"/api/projects/{project['id']}", headers=auth_headers(USER_A))).status_code == 403
    assert (await world.client.get(f"/api/scheduled-tasks/{task['id']}", headers=auth_headers(USER_A))).status_code == 404

    async def no_permissions(*args, **kwargs):
        return []

    monkeypatch.setattr("app.gateway.auth_middleware.resolve_route_permissions", no_permissions)
    for path in ("/api/scheduled-tasks",):
        response = await world.client.get(path, headers=headers)
        assert response.status_code == 403
        assert "Permission denied" in response.json()["detail"]


def test_project_operator_configuration_remains_closed_to_clients():
    from app.gateway.client_boundary import is_client_allowed_route

    assert not is_client_allowed_route("GET", "/api/projects/config")
