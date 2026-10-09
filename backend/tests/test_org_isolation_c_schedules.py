"""M3 lane C: scheduled tasks and their runs are organization-isolated.

Every schedule route answers 404 across organizations. A shared workspace's
tasks belong to its storage principal, so every active member sees and manages
them. Each task carries a ``scheduled_task`` delegation for its creator that the
scheduler re-reads before every launch, so a revoked owner fails closed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from org_isolation_fixtures import ORG_A, ORG_B, ORG_S, STORAGE_S, USER_A, USER_B, USER_C, acting_as, auth_headers, org_world  # noqa: F401
from sqlalchemy import func, select, update

from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.internal_auth import INTERNAL_OWNER_USER_ID_HEADER_NAME
from app.gateway.routers import scheduled_tasks
from app.scheduler.service import ScheduledTaskService
from deerflow.persistence.organizations.delegation import OrganizationDelegationRepository
from deerflow.persistence.organizations.model import OrganizationDelegationRow, OrganizationMemberRow
from deerflow.persistence.scheduled_task_runs import ScheduledTaskRunRepository
from deerflow.persistence.scheduled_task_runs.model import ScheduledTaskRunRow
from deerflow.persistence.scheduled_tasks import ScheduledTaskRepository
from deerflow.persistence.scheduled_tasks.model import ScheduledTaskRow
from deerflow.persistence.thread_meta.model import ThreadMetaRow
from deerflow.persistence.thread_meta.sql import ThreadMetaRepository

pytestmark = pytest.mark.asyncio

THREADS = {"thread-a": (USER_A, ORG_A), "thread-b": (USER_B, ORG_B), "thread-s": (STORAGE_S, ORG_S)}
TASK = {"title": "Daily digest", "prompt": "Summarize the day", "schedule_type": "cron", "schedule_spec": {"cron": "0 9 * * *"}, "timezone": "UTC"}
# Every route addressed by task id, with the body a mutation needs.
BY_ID_ROUTES = (("GET", ""), ("PATCH", ""), ("POST", "/pause"), ("POST", "/resume"), ("POST", "/trigger"), ("GET", "/runs"), ("DELETE", ""))


def _service(app: FastAPI, launch_run) -> ScheduledTaskService:
    return ScheduledTaskService(
        task_repo=app.state.scheduled_task_repo,
        task_run_repo=app.state.scheduled_task_run_repo,
        launch_run=launch_run,
        poll_interval_seconds=5,
        lease_seconds=60,
        max_concurrent_runs=3,
    )


@pytest_asyncio.fixture()
async def world(org_world, monkeypatch):  # noqa: F811
    monkeypatch.setattr(scheduled_tasks, "get_config", lambda: SimpleNamespace(scheduler=SimpleNamespace(min_once_delay_seconds=60)))
    async with org_world() as session, session.begin():
        for thread_id, (owner, organization_id) in THREADS.items():
            session.add(ThreadMetaRow(thread_id=thread_id, user_id=owner, organization_id=organization_id))

    launches: list[dict] = []

    async def launch_run(**kwargs):
        launches.append(kwargs)
        return {"run_id": f"run-{len(launches)}", "thread_id": kwargs["thread_id"]}

    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.include_router(scheduled_tasks.router)
    app.state.thread_store = ThreadMetaRepository(org_world)
    app.state.scheduled_task_repo = ScheduledTaskRepository(org_world)
    app.state.scheduled_task_run_repo = ScheduledTaskRunRepository(org_world)
    app.state.scheduled_task_service = _service(app, launch_run)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield SimpleNamespace(client=client, app=app, launches=launches, sf=org_world)


async def _create(world, actor, organization_id=None, **overrides) -> dict:
    response = await world.client.post("/api/scheduled-tasks", json=TASK | overrides, headers=auth_headers(actor, organization_id))
    assert response.status_code == 200, response.text
    return response.json()


async def _by_id(world, method, task_id, suffix, actor, organization_id=None):
    body = {"title": "hijacked"} if method == "PATCH" else None
    return await world.client.request(method, f"/api/scheduled-tasks/{task_id}{suffix}", json=body, headers=auth_headers(actor, organization_id))


async def _list(world, actor, organization_id=None) -> list[str]:
    response = await world.client.get("/api/scheduled-tasks", headers=auth_headers(actor, organization_id))
    assert response.status_code == 200, response.text
    return [task["id"] for task in response.json()]


async def _delegation(session_factory, task_id, organization_id, scope="runs:create"):
    return await OrganizationDelegationRepository(session_factory).resolve_active_delegation(subject_type="scheduled_task", subject_id=task_id, organization_id=organization_id, scope=scope)


async def _make_due(session_factory, *task_ids):
    async with session_factory() as session, session.begin():
        await session.execute(update(ScheduledTaskRow).where(ScheduledTaskRow.id.in_(task_ids)).values(next_run_at=datetime.now(UTC) - timedelta(minutes=1)))


async def test_every_schedule_route_is_not_found_across_organizations(world):
    task = await _create(world, USER_A)

    # b is another organization; a acting in S is the same person in another organization.
    for actor, organization_id in ((USER_B, None), (USER_A, ORG_S), (USER_C, None)):
        assert task["id"] not in await _list(world, actor, organization_id)
        for method, suffix in BY_ID_ROUTES:
            response = await _by_id(world, method, task["id"], suffix, actor, organization_id)
            assert response.status_code == 404, (actor, organization_id, method, suffix, response.text)
        thread_list = await world.client.get("/api/threads/thread-a/scheduled-tasks", headers=auth_headers(actor, organization_id))
        assert thread_list.status_code == 404

    # The probes changed nothing: no run, no edit, no revoked delegation.
    assert world.launches == []
    owner_view = (await _by_id(world, "GET", task["id"], "", USER_A)).json()
    assert (owner_view["title"], owner_view["status"]) == (TASK["title"], "enabled")
    assert await _delegation(world.sf, task["id"], ORG_A) is not None


async def test_attaching_a_schedule_to_another_organizations_thread_is_not_found(world):
    reuse = {"context_mode": "reuse_thread"}
    for actor, organization_id, foreign_thread in ((USER_A, None, "thread-b"), (USER_A, None, "thread-s"), (USER_A, ORG_S, "thread-a"), (USER_A, ORG_S, "thread-b")):
        response = await world.client.post("/api/scheduled-tasks", json=TASK | reuse | {"thread_id": foreign_thread}, headers=auth_headers(actor, organization_id))
        assert response.status_code == 404, (actor, organization_id, foreign_thread, response.text)

    private_task = await _create(world, USER_A)
    shared_task = await _create(world, USER_A, ORG_S)
    for task, organization_id, foreign_thread in ((private_task, None, "thread-b"), (private_task, None, "thread-s"), (shared_task, ORG_S, "thread-a")):
        response = await world.client.patch(f"/api/scheduled-tasks/{task['id']}", json=reuse | {"thread_id": foreign_thread}, headers=auth_headers(USER_A, organization_id))
        assert response.status_code == 404, (task["id"], foreign_thread, response.text)

    # Positive control: S's own thread attaches, under S's storage principal and organization.
    attached = await _create(world, USER_A, ORG_S, **reuse, thread_id="thread-s")
    thread_list = await world.client.get("/api/threads/thread-s/scheduled-tasks", headers=auth_headers(USER_C, ORG_S))
    assert thread_list.status_code == 200
    assert [task["id"] for task in thread_list.json()] == [attached["id"]]
    async with world.sf() as session:
        row = await session.get(ScheduledTaskRow, attached["id"])
        assert (row.user_id, row.organization_id, row.thread_id) == (STORAGE_S, ORG_S, "thread-s")
        # Refused attaches created nothing.
        assert await session.scalar(select(func.count()).select_from(ScheduledTaskRow)) == 3


async def test_shared_workspace_co_member_sees_and_manages_its_tasks(world):
    task = await _create(world, USER_A, ORG_S)
    async with world.sf() as session:
        row = await session.get(ScheduledTaskRow, task["id"])
        assert (row.user_id, row.organization_id) == (STORAGE_S, ORG_S)

    assert await _list(world, USER_C, ORG_S) == [task["id"]]
    assert (await _by_id(world, "GET", task["id"], "", USER_C, ORG_S)).status_code == 200
    patched = await world.client.patch(f"/api/scheduled-tasks/{task['id']}", json={"title": "Renamed by c"}, headers=auth_headers(USER_C, ORG_S))
    assert (patched.status_code, patched.json()["title"]) == (200, "Renamed by c")
    paused = await _by_id(world, "POST", task["id"], "/pause", USER_C, ORG_S)
    assert (paused.status_code, paused.json()["status"]) == (200, "paused")
    resumed = await _by_id(world, "POST", task["id"], "/resume", USER_C, ORG_S)
    assert (resumed.status_code, resumed.json()["status"]) == (200, "enabled")
    triggered = await _by_id(world, "POST", task["id"], "/trigger", USER_C, ORG_S)
    assert triggered.status_code == 200, triggered.text
    assert [launch["metadata"]["scheduled_task_id"] for launch in world.launches] == [task["id"]]
    runs = await _by_id(world, "GET", task["id"], "/runs", USER_C, ORG_S)
    assert (runs.status_code, [run["task_id"] for run in runs.json()]) == (200, [task["id"]])

    # The same person outside S, and an outsider, see nothing.
    assert await _list(world, USER_A) == []
    assert (await _by_id(world, "GET", task["id"], "", USER_A)).status_code == 404
    assert (await _by_id(world, "GET", task["id"], "", USER_B)).status_code == 404


async def test_creating_a_task_grants_a_delegation_and_deleting_it_revokes_it(world):
    task = await _create(world, USER_A, ORG_S)

    delegation = await _delegation(world.sf, task["id"], ORG_S)
    assert delegation is not None
    # The creator owns it; the launcher acts in S under S's storage principal; launching runs needs only runs:create.
    assert (delegation.owner_user_id, delegation.organization.id, delegation.organization.storage_user_id) == (USER_A, ORG_S, STORAGE_S)
    assert delegation.scopes == frozenset({"runs:create"})
    assert await _delegation(world.sf, task["id"], ORG_S, scope="threads:delete") is None

    private_task = await _create(world, USER_B)
    assert (await _delegation(world.sf, private_task["id"], ORG_B)).owner_user_id == USER_B

    deleted = await _by_id(world, "DELETE", task["id"], "", USER_C, ORG_S)
    assert deleted.status_code == 200
    assert await _delegation(world.sf, task["id"], ORG_S) is None
    async with world.sf() as session:
        statuses = (await session.execute(select(OrganizationDelegationRow.status).where(OrganizationDelegationRow.subject_id == task["id"]))).scalars().all()
    assert statuses == ["revoked"]
    assert await _delegation(world.sf, private_task["id"], ORG_B) is not None


async def test_revoked_owner_membership_fails_the_next_occurrence_closed(world):
    kept = await _create(world, USER_C, ORG_S, title="c's task")
    lost = await _create(world, USER_A, ORG_S, title="a's task")
    async with world.sf() as session, session.begin():
        await session.execute(update(OrganizationMemberRow).where(OrganizationMemberRow.organization_id == ORG_S, OrganizationMemberRow.user_id == USER_A).values(status="revoked"))
    await _make_due(world.sf, kept["id"], lost["id"])

    await world.app.state.scheduled_task_service.run_once(now=datetime.now(UTC))

    # c is still active, so c's task launches in the same poll; a's task starts no run.
    assert [launch["metadata"]["scheduled_task_id"] for launch in world.launches] == [kept["id"]]
    async with world.sf() as session:
        occurrences = (await session.execute(select(ScheduledTaskRunRow).where(ScheduledTaskRunRow.task_id == lost["id"]))).scalars().all()
    assert [(row.status, row.run_id) for row in occurrences] == [("failed", None)]
    assert "delegation" in occurrences[0].error

    # A manual trigger by an active member cannot borrow the revoked owner's authority either.
    triggered = await _by_id(world, "POST", lost["id"], "/trigger", USER_C, ORG_S)
    assert triggered.status_code == 502
    assert len(world.launches) == 1


async def test_repository_adds_the_organization_filter_beside_the_user_filter(org_world):  # noqa: F811
    repo = ScheduledTaskRepository(org_world)
    now = datetime.now(UTC)
    async with org_world() as session, session.begin():
        # Same audit owner; only the organization differs: a's own row, a NULL (quarantined) row, and a conflicting stamp.
        for task_id, organization_id in (("task-own", ORG_A), ("task-quarantined", None), ("task-conflicting", ORG_S)):
            session.add(
                ScheduledTaskRow(
                    id=task_id, user_id=USER_A, organization_id=organization_id, thread_id="thread-a", title="t", prompt="p", schedule_type="cron", schedule_spec={"cron": "0 9 * * *"}, timezone="UTC", created_at=now, updated_at=now
                )
            )

    with acting_as(USER_A):
        assert [task["id"] for task in await repo.list_by_user(USER_A)] == ["task-own"]
        assert [task["id"] for task in await repo.list_by_user_and_thread(USER_A, "thread-a")] == ["task-own"]
        for hidden in ("task-quarantined", "task-conflicting"):
            assert await repo.get(hidden, user_id=USER_A) is None
            assert await repo.update(hidden, user_id=USER_A, updates={"title": "x"}) is None
            assert await repo.pause_with_queue_cancellation(hidden, user_id=USER_A, error="e", now=now) == "not_found"
            assert await repo.delete_with_queue_cancellation(hidden, user_id=USER_A, error="e", now=now) == "not_found"
        assert await repo.get("task-own", user_id=USER_A) is not None

    # Internal and background callers establish no organization: the user filter alone applies, as before M3.
    assert {task["id"] for task in await repo.list_by_user(USER_A)} == {"task-own", "task-quarantined", "task-conflicting"}


async def test_scheduled_launcher_acts_through_its_delegation_not_a_raw_owner_header(world, monkeypatch):
    """``services.launch_scheduled_thread_run`` acts through the task's delegation.

    The scheduler resolves the delegation before launching; the launcher sets
    ``state.organization_id`` to its organization, ``state.storage_user_id`` to
    that organization's storage principal, ``state.actor_user_id`` to the
    delegation owner, and sends no owner header.
    """
    from app.gateway import services

    task = await _create(world, USER_A, ORG_S)
    captured = []

    async def start_run(body, thread_id, request, *, idempotency_key=None):
        captured.append(request)
        return SimpleNamespace(run_id="run-1", thread_id=thread_id)

    monkeypatch.setattr(services, "start_run", start_run)
    service = _service(world.app, lambda **kwargs: services.launch_scheduled_thread_run(app=world.app, **kwargs))
    await _make_due(world.sf, task["id"])

    await service.run_once(now=datetime.now(UTC))

    (request,) = captured  # not an AssertionError: a launch that never happened fails this test for real
    assert INTERNAL_OWNER_USER_ID_HEADER_NAME not in request.headers
    assert (request.state.organization_id, request.state.storage_user_id, request.state.actor_user_id) == (ORG_S, STORAGE_S, USER_A)
