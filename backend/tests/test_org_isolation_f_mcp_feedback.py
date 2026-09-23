"""M3 lane F: organization isolation for durable MCP tasks and feedback.

Covers:
- MCP task ``create()`` refuses to attach to an existing-but-ownerless thread,
  and refuses when the active organization disagrees with the thread's
  storage-principal-derived organization (``mcp_tasks/sql.py``).
- MCP task list/get/cancel routes return 404 across organizations, and behave
  identically whether ``mcp_tasks.enabled`` is on or off
  (``app/gateway/routers/mcp_tasks.py``).
- Feedback create/list/delete are organization-scoped, including the case
  where the same person belongs to two organizations
  (``persistence/feedback/sql.py``).
- The known bug: feedback submitted in a shared workspace used to 500
  because the repository checked the person's id against the thread's
  storage-principal ``user_id``. Fixed feedback is stored with the person's
  own ``user_id`` and the workspace's organization
  (``app/gateway/routers/feedback.py``).
- REQUIREMENT FOR LANE 0 (xfail): the MCP notification launcher
  (``app/gateway/services.py::launch_mcp_task_notification_run``, roughly
  lines 2196-2269) must resolve an active ``organization_delegation`` for the
  task's owner before launching the delivery run. It currently trusts the
  caller-supplied ``owner_user_id`` alone, the internal-token-plus-header
  pattern contract section 4 forbids.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import FastAPI
from org_isolation_fixtures import (  # noqa: F401 -- org_world is used as a fixture
    ORG_A,
    ORG_B,
    ORG_S,
    STORAGE_S,
    USER_A,
    USER_B,
    USER_C,
    acting_as,
    auth_headers,
    org_world,
)

from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.routers import feedback as feedback_router
from app.gateway.routers import mcp_tasks as mcp_tasks_router
from app.mcp_tasks import McpTaskService
from deerflow.mcp.tasks import McpTaskDriverRegistry
from deerflow.persistence.feedback.sql import FeedbackRepository
from deerflow.persistence.mcp_tasks.sql import McpTaskRepository
from deerflow.persistence.organizations.resolution import OrganizationMismatchError
from deerflow.persistence.run.sql import RunRepository
from deerflow.persistence.thread_meta.sql import ThreadMetaRepository
from deerflow.runtime.user_context import AUTO

pytestmark = pytest.mark.asyncio


def _build_app(session_factory) -> FastAPI:
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.include_router(mcp_tasks_router.router)
    app.include_router(feedback_router.router)
    app.state.thread_store = ThreadMetaRepository(session_factory)
    app.state.run_store = RunRepository(session_factory)
    app.state.feedback_repo = FeedbackRepository(session_factory)
    mcp_task_repo = McpTaskRepository(session_factory)
    app.state.mcp_task_repo = mcp_task_repo
    app.state.mcp_task_service = McpTaskService(
        repository=mcp_task_repo,
        drivers=McpTaskDriverRegistry(),
        poll_interval_seconds=30,
        lease_seconds=60,
        max_concurrent_polls=5,
        tracking_degraded_after_errors=3,
    )
    app.state.mcp_tasks_available = True
    return app


def _mcp_task_kwargs(task_id: str, **overrides) -> dict:
    base = dict(
        run_id=None,
        tool_call_id=None,
        server_name="reports",
        driver_name="fake",
        remote_task_id=f"remote-{task_id}",
        task_name="Generate report",
        status="working",
        result=None,
        result_preview=None,
        result_truncated=False,
        result_artifact=None,
        error=None,
        input_required=None,
        next_poll_at=None,
    )
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# create(): ownerless threads and cross-organization thread attachment
# ---------------------------------------------------------------------------


async def test_create_rejects_existing_ownerless_thread(org_world):  # noqa: F811 (pytest fixture imported above)
    session_factory = org_world
    thread_repo = ThreadMetaRepository(session_factory)
    # An existing thread row with no owner (legacy/shared data) -- distinct
    # from "thread_id has no row at all", which stays tolerated for
    # untracked-legacy-thread backward compatibility.
    await thread_repo.create("thread-orphan", user_id=None)

    task_repo = McpTaskRepository(session_factory)
    with acting_as(USER_A, ORG_A), pytest.raises(ValueError, match="no owner"):
        await task_repo.create(
            task_id="task-orphan",
            user_id=USER_A,
            thread_id="thread-orphan",
            **_mcp_task_kwargs(task_id="task-orphan"),
        )

    assert await task_repo.get("task-orphan", user_id=USER_A) is None


async def test_create_tolerates_untracked_thread_with_no_row(org_world):  # noqa: F811 (pytest fixture imported above)
    """No thread row at all keeps the pre-existing legacy-thread tolerance.

    The task still gets stamped with the caller's own active organization
    (via ``organization_for_write``) rather than being quarantined, since
    there is no parent row to disagree with the caller's server-resolved org.
    """
    session_factory = org_world
    task_repo = McpTaskRepository(session_factory)
    with acting_as(USER_A, ORG_A):
        created = await task_repo.create(
            task_id="task-untracked",
            user_id=USER_A,
            thread_id="thread-never-created",
            **_mcp_task_kwargs(task_id="task-untracked"),
        )
    assert created["organization_id"] == ORG_A

    # With no active organization context at all (background/internal caller,
    # matching the pre-existing repository test suite's autouse fixture,
    # which sets only the actor contextvar) the row stays quarantined (None),
    # unchanged from before this fix.
    task_repo_2 = McpTaskRepository(session_factory)
    created_no_context = await task_repo_2.create(
        task_id="task-untracked-no-context",
        user_id=USER_A,
        thread_id="thread-never-created-2",
        **_mcp_task_kwargs(task_id="task-untracked-no-context"),
    )
    assert created_no_context["organization_id"] is None


async def test_create_rejects_thread_from_another_organization(org_world):  # noqa: F811 (pytest fixture imported above)
    """Active org (acting_as ORG_A) disagreeing with the thread's own org is refused."""
    session_factory = org_world
    thread_repo = ThreadMetaRepository(session_factory)
    with acting_as(USER_A, ORG_S):
        await thread_repo.create("thread-s", user_id=AUTO)

    task_repo = McpTaskRepository(session_factory)
    with acting_as(USER_A, ORG_A), pytest.raises(OrganizationMismatchError):
        # user_id matches the thread's real owner (STORAGE_S), but the
        # active organization context is ORG_A: organization_for_write must
        # reject this rather than silently stamping the thread's org.
        await task_repo.create(
            task_id="task-cross-org",
            user_id=STORAGE_S,
            thread_id="thread-s",
            **_mcp_task_kwargs(task_id="task-cross-org"),
        )


async def test_create_rejects_thread_owned_by_a_different_storage_principal(org_world):  # noqa: F811 (pytest fixture imported above)
    session_factory = org_world
    thread_repo = ThreadMetaRepository(session_factory)
    with acting_as(USER_A, ORG_A):
        await thread_repo.create("thread-a", user_id=AUTO)

    task_repo = McpTaskRepository(session_factory)
    with acting_as(USER_B, ORG_B), pytest.raises(ValueError, match="different user"):
        await task_repo.create(
            task_id="task-b-on-a",
            user_id=USER_B,
            thread_id="thread-a",
            **_mcp_task_kwargs(task_id="task-b-on-a"),
        )


# ---------------------------------------------------------------------------
# MCP task list/get/cancel: 404 across organizations
# ---------------------------------------------------------------------------


async def _seed_mcp_task(session_factory, *, actor, organization_id, thread_id, task_id) -> None:
    thread_repo = ThreadMetaRepository(session_factory)
    task_repo = McpTaskRepository(session_factory)
    storage_user_id = STORAGE_S if organization_id == ORG_S else actor
    with acting_as(actor, organization_id):
        await thread_repo.create(thread_id, user_id=AUTO)
        await task_repo.create(
            task_id=task_id,
            user_id=storage_user_id,
            thread_id=thread_id,
            **_mcp_task_kwargs(task_id=task_id),
        )


async def test_mcp_task_routes_visible_within_owning_organization(org_world):  # noqa: F811 (pytest fixture imported above)
    session_factory = org_world
    await _seed_mcp_task(session_factory, actor=USER_A, organization_id=ORG_A, thread_id="thread-a", task_id="task-a")

    app = _build_app(session_factory)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        listing = await client.get("/api/threads/thread-a/mcp-tasks", headers=auth_headers(USER_A))
        assert listing.status_code == 200
        assert [item["task_id"] for item in listing.json()] == ["task-a"]

        detail = await client.get("/api/threads/thread-a/mcp-tasks/task-a", headers=auth_headers(USER_A))
        assert detail.status_code == 200
        assert detail.json()["task_id"] == "task-a"


async def test_mcp_task_routes_404_across_organizations(org_world):  # noqa: F811 (pytest fixture imported above)
    session_factory = org_world
    await _seed_mcp_task(session_factory, actor=USER_A, organization_id=ORG_S, thread_id="thread-s", task_id="task-s")

    app = _build_app(session_factory)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # USER_B has no membership in ORG_S at all: the thread owner_check
        # already denies (proves the router+repo composition).
        for path in ("/api/threads/thread-s/mcp-tasks", "/api/threads/thread-s/mcp-tasks/task-s"):
            result = await client.get(path, headers=auth_headers(USER_B))
            assert result.status_code == 404, path

        cancel = await client.post("/api/threads/thread-s/mcp-tasks/task-s/cancel", headers=auth_headers(USER_B))
        assert cancel.status_code == 404

        # USER_A owns both ORG_A (private) and ORG_S (shared): acting in
        # ORG_A must not see the task that lives in ORG_S, even though it is
        # the same real person.
        for path in ("/api/threads/thread-s/mcp-tasks", "/api/threads/thread-s/mcp-tasks/task-s"):
            result = await client.get(path, headers=auth_headers(USER_A, ORG_A))
            assert result.status_code == 404, path


async def test_mcp_tasks_disabled_keeps_read_routes_identical(org_world):  # noqa: F811 (pytest fixture imported above)
    """mcp_tasks.enabled=false on live: list/get stay 200, cancel still 503."""
    session_factory = org_world
    await _seed_mcp_task(session_factory, actor=USER_A, organization_id=ORG_A, thread_id="thread-a", task_id="task-a")

    app = _build_app(session_factory)
    app.state.mcp_tasks_available = False
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        listing = await client.get("/api/threads/thread-a/mcp-tasks", headers=auth_headers(USER_A))
        assert listing.status_code == 200
        assert [item["task_id"] for item in listing.json()] == ["task-a"]

        detail = await client.get("/api/threads/thread-a/mcp-tasks/task-a", headers=auth_headers(USER_A))
        assert detail.status_code == 200

        cancel = await client.post("/api/threads/thread-a/mcp-tasks/task-a/cancel", headers=auth_headers(USER_A))
        assert cancel.status_code == 503


# ---------------------------------------------------------------------------
# Feedback: the shared-workspace 500 bug, and organization scoping
# ---------------------------------------------------------------------------


async def _seed_thread_and_run(session_factory, *, actor, organization_id, thread_id, run_id) -> None:
    thread_repo = ThreadMetaRepository(session_factory)
    run_repo = RunRepository(session_factory)
    with acting_as(actor, organization_id):
        await thread_repo.create(thread_id, user_id=AUTO)
        await run_repo.put(run_id, thread_id=thread_id, user_id=AUTO, status="success")


async def test_feedback_shared_workspace_upsert_returns_2xx_with_person_and_org(org_world):  # noqa: F811 (pytest fixture imported above)
    session_factory = org_world
    await _seed_thread_and_run(session_factory, actor=USER_A, organization_id=ORG_S, thread_id="thread-s", run_id="run-s")

    app = _build_app(session_factory)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # USER_C is an admin member of the shared workspace S, distinct from
        # its storage principal STORAGE_S. Before the fix this 500'd.
        response = await client.put(
            "/api/threads/thread-s/runs/run-s/feedback",
            headers=auth_headers(USER_C, ORG_S),
            json={"rating": 1, "comment": "nice"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["user_id"] == USER_C
        assert body["rating"] == 1

    feedback_repo = FeedbackRepository(session_factory)
    rows = await feedback_repo.list_by_run("thread-s", "run-s", user_id=None)
    assert len(rows) == 1
    assert rows[0]["user_id"] == USER_C
    assert rows[0]["organization_id"] == ORG_S


async def test_feedback_shared_workspace_create_returns_2xx(org_world):  # noqa: F811 (pytest fixture imported above)
    session_factory = org_world
    await _seed_thread_and_run(session_factory, actor=USER_A, organization_id=ORG_S, thread_id="thread-s2", run_id="run-s2")

    app = _build_app(session_factory)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/threads/thread-s2/runs/run-s2/feedback",
            headers=auth_headers(USER_C, ORG_S),
            json={"rating": -1, "message_id": "msg-1"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["user_id"] == USER_C


async def test_feedback_list_and_delete_round_trip_in_shared_workspace(org_world):  # noqa: F811 (pytest fixture imported above)
    session_factory = org_world
    await _seed_thread_and_run(session_factory, actor=USER_A, organization_id=ORG_S, thread_id="thread-s3", run_id="run-s3")

    app = _build_app(session_factory)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        upsert = await client.put(
            "/api/threads/thread-s3/runs/run-s3/feedback",
            headers=auth_headers(USER_C, ORG_S),
            json={"rating": 1},
        )
        assert upsert.status_code == 200
        feedback_id = upsert.json()["feedback_id"]

        listing = await client.get("/api/threads/thread-s3/runs/run-s3/feedback", headers=auth_headers(USER_C, ORG_S))
        assert listing.status_code == 200
        assert [item["feedback_id"] for item in listing.json()] == [feedback_id]

        deleted = await client.delete(
            f"/api/threads/thread-s3/runs/run-s3/feedback/{feedback_id}",
            headers=auth_headers(USER_C, ORG_S),
        )
        assert deleted.status_code == 200, deleted.text

        listing_after = await client.get("/api/threads/thread-s3/runs/run-s3/feedback", headers=auth_headers(USER_C, ORG_S))
        assert listing_after.json() == []


async def test_feedback_routes_404_across_organizations(org_world):  # noqa: F811 (pytest fixture imported above)
    session_factory = org_world
    await _seed_thread_and_run(session_factory, actor=USER_A, organization_id=ORG_S, thread_id="thread-s4", run_id="run-s4")

    app = _build_app(session_factory)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        upsert = await client.put(
            "/api/threads/thread-s4/runs/run-s4/feedback",
            headers=auth_headers(USER_A, ORG_S),
            json={"rating": 1},
        )
        assert upsert.status_code == 200
        feedback_id = upsert.json()["feedback_id"]

        # USER_B has no membership in ORG_S: denied before even reaching the
        # feedback repository, via the thread owner_check.
        for response in (
            await client.get("/api/threads/thread-s4/runs/run-s4/feedback", headers=auth_headers(USER_B)),
            await client.delete(f"/api/threads/thread-s4/runs/run-s4/feedback/{feedback_id}", headers=auth_headers(USER_B)),
        ):
            assert response.status_code == 404


async def test_feedback_repository_denies_same_person_across_organizations(org_world):  # noqa: F811 (pytest fixture imported above)
    """USER_A owns both ORG_A and ORG_S; a feedback id from one must not resolve in the other."""
    session_factory = org_world
    await _seed_thread_and_run(session_factory, actor=USER_A, organization_id=ORG_A, thread_id="thread-a5", run_id="run-a5")
    await _seed_thread_and_run(session_factory, actor=USER_A, organization_id=ORG_S, thread_id="thread-s5", run_id="run-s5")

    feedback_repo = FeedbackRepository(session_factory)
    with acting_as(USER_A, ORG_A):
        in_a = await feedback_repo.create(run_id="run-a5", thread_id="thread-a5", rating=1)
    with acting_as(USER_A, ORG_S):
        in_s = await feedback_repo.create(run_id="run-s5", thread_id="thread-s5", rating=-1)

    with acting_as(USER_A, ORG_A):
        # Same actor id (USER_A) on both rows -- only the organization filter
        # can tell these apart.
        assert await feedback_repo.get(in_s["feedback_id"]) is None
        assert await feedback_repo.delete(in_s["feedback_id"]) is False
        assert (await feedback_repo.get(in_a["feedback_id"]))["feedback_id"] == in_a["feedback_id"]

    with acting_as(USER_A, ORG_S):
        assert await feedback_repo.get(in_a["feedback_id"]) is None
        assert (await feedback_repo.get(in_s["feedback_id"]))["feedback_id"] == in_s["feedback_id"]


# ---------------------------------------------------------------------------
# REQUIREMENT FOR LANE 0: MCP notification launcher delegation check
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason="needs lane 0 phase 2: services.py launch_mcp_task_notification_run must "
    "resolve an active organization_delegation for the task's owner before launching; "
    "today it trusts owner_user_id via the internal-token-plus-header pattern alone",
)
async def test_mcp_notification_launcher_denies_without_active_delegation():
    from app.gateway.services import launch_mcp_task_notification_run

    start_run_mock = AsyncMock(return_value=SimpleNamespace(run_id="run-notification", thread_id="thread-notification"))
    with patch("app.gateway.services.start_run", start_run_mock):
        with pytest.raises(PermissionError):
            await launch_mcp_task_notification_run(
                app=SimpleNamespace(state=SimpleNamespace()),
                thread_id="thread-notification",
                assistant_id="lead_agent",
                owner_user_id=USER_A,
                task_id="task-1",
                dispatch_version=1,
                dispatch_attempt=1,
                event={"status": "completed", "result": "done"},
            )
        start_run_mock.assert_not_called()
