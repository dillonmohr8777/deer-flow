"""Tests for GET /api/briefs/today (the personal morning brief).

Covers:
1. Empty state
2. Client-linked project scope, with fallback to the caller's own active projects
3. Activity assembly: new threads/runs (success + failure), shelf documents,
   scheduled-task outcomes (success + failure); 24h cutoff
4. Due-today scheduled tasks, including the tz_offset_minutes local-day window
5. Waiting-on-you: interrupted runs, unanswered clarifications, only the latest
   run per thread counts, oldest-first ordering
6. Cross-user isolation for assigned clients inside one shared workspace
   (activity/threads/runs are workspace-shared there by design; only the
   client roster is actor-scoped; see briefs.py's module docstring)
7. 503 without a SQL database backend

Uses the real ``clients`` + ``briefs`` routers behind real ``AuthMiddleware`` and
the shared ``org_isolation_fixtures`` world (mirrors test_org_isolation_h_clients.py),
because the client-roster scope genuinely depends on AuthMiddleware-resolved actor
identity, not just the simpler owner/org columns console.py's lighter stub harness
covers. Timestamps use a router-frozen ``NOW`` (mirrors test_console_router.py) so
the 24h/today windows are deterministic regardless of wall-clock run time.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import pytest_asyncio
from org_isolation_fixtures import ORG_A, ORG_S, USER_A, USER_C, auth_headers, org_world  # noqa: F401

from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.routers import briefs, clients
from deerflow.persistence.clients import ClientRepository
from deerflow.persistence.models.run_event import RunEventRow
from deerflow.persistence.projects.model import ProjectDocumentRow, ProjectRow
from deerflow.persistence.run.model import RunRow
from deerflow.persistence.scheduled_task_runs.model import ScheduledTaskRunRow
from deerflow.persistence.scheduled_tasks.model import ScheduledTaskRow
from deerflow.persistence.thread_meta.model import ThreadMetaRow

pytestmark = pytest.mark.asyncio

# Pinned to noon UTC so hour-level seed offsets never cross a midnight boundary
# (see test_console_router.py's identical rationale).
NOW = datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0)


class _FrozenDatetime(datetime):
    _frozen: datetime | None = None

    @classmethod
    def now(cls, tz=None):
        if cls._frozen is None:  # pragma: no cover - defensive fallback
            return super().now(tz)
        return cls._frozen if tz is None else cls._frozen.astimezone(tz)


def _build_app(session_factory, monkeypatch) -> httpx.AsyncClient:
    monkeypatch.setattr(briefs, "get_session_factory", lambda: session_factory)
    _FrozenDatetime._frozen = NOW
    monkeypatch.setattr(briefs, "datetime", _FrozenDatetime)

    from fastapi import FastAPI

    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.state.client_repo = ClientRepository(session_factory)
    app.include_router(clients.router)
    app.include_router(briefs.router)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _create_client_with_assignment(client: httpx.AsyncClient, headers: dict[str, str], name: str) -> str:
    resp = await client.post("/api/clients", json={"display_name": name}, headers=headers)
    assert resp.status_code == 201, resp.text
    client_id = resp.json()["id"]
    resp = await client.post(f"/api/clients/{client_id}/assignments", json={"user_id": USER_A, "role": "account_manager"}, headers=headers)
    assert resp.status_code == 201, resp.text
    return client_id


def _project(**overrides) -> ProjectRow:
    base: dict[str, Any] = dict(
        id="proj-default",
        user_id=USER_A,
        organization_id=ORG_A,
        client_id=None,
        name="Untitled project",
        instructions="",
        presentation={},
        status="active",
        created_at=NOW,
        updated_at=NOW,
    )
    base.update(overrides)
    return ProjectRow(**base)


def _thread(**overrides) -> ThreadMetaRow:
    base: dict[str, Any] = dict(
        thread_id="thread-default",
        user_id=USER_A,
        organization_id=ORG_A,
        project_id=None,
        display_name="A conversation",
        status="idle",
        metadata_json={},
        created_at=NOW,
        updated_at=NOW,
    )
    base.update(overrides)
    return ThreadMetaRow(**base)


def _scheduled_task(**overrides) -> ScheduledTaskRow:
    base: dict[str, Any] = dict(
        id="task-default",
        user_id=USER_A,
        organization_id=ORG_A,
        title="A scheduled task",
        prompt="x",
        schedule_type="cron",
        timezone="UTC",
        status="enabled",
        created_at=NOW,
        updated_at=NOW,
    )
    base.update(overrides)
    return ScheduledTaskRow(**base)


def _run(**overrides) -> RunRow:
    base: dict[str, Any] = dict(
        run_id="run-default",
        thread_id="thread-default",
        user_id=USER_A,
        organization_id=ORG_A,
        status="success",
        operation_kind="run",
        created_at=NOW,
        updated_at=NOW,
    )
    base.update(overrides)
    return RunRow(**base)


@pytest_asyncio.fixture()
async def seeded(org_world, monkeypatch):  # noqa: F811
    """A client assigned to USER_A, its linked project, and one recent thread+run."""
    session_factory = org_world
    client = _build_app(session_factory, monkeypatch)
    async with client:
        client_id = await _create_client_with_assignment(client, auth_headers(USER_A), "Acme")
        async with session_factory() as session:
            session.add_all(
                [
                    _project(id="proj-1", client_id=client_id, name="Acme Website"),
                    _thread(thread_id="t1", project_id="proj-1", display_name="Kickoff notes", created_at=NOW - timedelta(hours=1)),
                    _run(run_id="r1", thread_id="t1", status="success", created_at=NOW - timedelta(hours=1)),
                ]
            )
            await session.commit()
        yield client, client_id


class TestEmptyState:
    async def test_no_data_returns_empty_lists(self, org_world, monkeypatch):  # noqa: F811
        client = _build_app(org_world, monkeypatch)
        async with client:
            resp = await client.get("/api/briefs/today", headers=auth_headers(USER_A))
        assert resp.status_code == 200
        data = resp.json()
        assert data["assigned_clients"] == []
        assert data["activity"] == []
        assert data["due_today"] == []
        assert data["waiting_on_you"] == []


class TestScopeAndActivity:
    async def test_client_linked_project_activity(self, seeded):
        client, client_id = seeded
        resp = await client.get("/api/briefs/today", headers=auth_headers(USER_A))
        assert resp.status_code == 200
        data = resp.json()
        assert [c["id"] for c in data["assigned_clients"]] == [client_id]
        # The fixture also seeds a run on t1 within the last 24h, so it's a
        # "run_success" item alongside the "thread" item asserted below.
        assert {item["kind"] for item in data["activity"]} == {"thread", "run_success"}
        [item] = [item for item in data["activity"] if item["kind"] == "thread"]
        assert item["title"] == "Kickoff notes"
        assert item["thread_id"] == "t1"
        assert item["project_name"] == "Acme Website"
        assert item["client_id"] == client_id
        assert item["client_name"] == "Acme"

    async def test_falls_back_to_own_active_projects_when_none_linked(self, org_world, monkeypatch):  # noqa: F811
        session_factory = org_world
        client = _build_app(session_factory, monkeypatch)
        async with client:
            client_id = await _create_client_with_assignment(client, auth_headers(USER_A), "Acme")
            async with session_factory() as session:
                # No project links to this client, so the fallback must still
                # surface the caller's own active project so the brief is useful today.
                session.add_all(
                    [
                        _project(id="proj-own", name="My scratch project"),
                        _thread(thread_id="t-own", project_id="proj-own", display_name="Loose thread", created_at=NOW - timedelta(hours=2)),
                    ]
                )
                # An archived project must not leak into the fallback scope.
                session.add(_project(id="proj-archived", name="Old", status="archived"))
                await session.commit()

            resp = await client.get("/api/briefs/today", headers=auth_headers(USER_A))
        assert resp.status_code == 200
        data = resp.json()
        assert [c["id"] for c in data["assigned_clients"]] == [client_id]
        [item] = data["activity"]
        assert item["thread_id"] == "t-own"
        assert item["project_name"] == "My scratch project"
        assert item["client_id"] is None  # fallback project isn't linked to any client

    async def test_activity_excludes_older_than_24h(self, org_world, monkeypatch):  # noqa: F811
        session_factory = org_world
        client = _build_app(session_factory, monkeypatch)
        async with client:
            await _create_client_with_assignment(client, auth_headers(USER_A), "Acme")
            async with session_factory() as session:
                session.add_all(
                    [
                        _project(id="proj-1", name="Recent work"),
                        _thread(thread_id="t-recent", project_id="proj-1", display_name="Fresh", created_at=NOW - timedelta(hours=1)),
                        _thread(thread_id="t-stale", project_id="proj-1", display_name="Stale", created_at=NOW - timedelta(hours=25)),
                    ]
                )
                await session.commit()
            resp = await client.get("/api/briefs/today", headers=auth_headers(USER_A))
        data = resp.json()
        titles = {item["title"] for item in data["activity"]}
        assert titles == {"Fresh"}

    async def test_runs_and_documents_and_scheduled_outcomes(self, org_world, monkeypatch):  # noqa: F811
        session_factory = org_world
        client = _build_app(session_factory, monkeypatch)
        async with client:
            await _create_client_with_assignment(client, auth_headers(USER_A), "Acme")
            async with session_factory() as session:
                session.add_all(
                    [
                        _project(id="proj-1", name="Acme Website"),
                        _thread(thread_id="t1", project_id="proj-1", display_name="Chat one"),
                        _run(run_id="r-ok", thread_id="t1", status="success", created_at=NOW - timedelta(hours=1), updated_at=NOW - timedelta(hours=1)),
                        _run(run_id="r-bad", thread_id="t1", status="error", error="Boom: provider exploded", created_at=NOW - timedelta(minutes=30), updated_at=NOW - timedelta(minutes=30)),
                        ProjectDocumentRow(
                            id="doc-1",
                            project_id="proj-1",
                            user_id=USER_A,
                            organization_id=ORG_A,
                            name="brief.pdf",
                            stored_relpath="x",
                            sha256="a" * 64,
                            size_bytes=10,
                            created_at=NOW - timedelta(hours=3),
                            updated_at=NOW - timedelta(hours=3),
                        ),
                        ProjectDocumentRow(
                            id="doc-trashed",
                            project_id="proj-1",
                            user_id=USER_A,
                            organization_id=ORG_A,
                            name="gone.pdf",
                            stored_relpath="y",
                            sha256="b" * 64,
                            size_bytes=10,
                            trashed_at=NOW - timedelta(minutes=5),
                            created_at=NOW - timedelta(hours=1),
                            updated_at=NOW - timedelta(minutes=5),
                        ),
                        ScheduledTaskRow(
                            id="task-1",
                            user_id=USER_A,
                            organization_id=ORG_A,
                            title="Weekly digest",
                            prompt="Summarize",
                            schedule_type="cron",
                            timezone="UTC",
                            status="enabled",
                            created_at=NOW,
                            updated_at=NOW,
                        ),
                        ScheduledTaskRunRow(
                            id="occ-1",
                            task_id="task-1",
                            organization_id=ORG_A,
                            thread_id="t-occ",
                            scheduled_for=NOW - timedelta(hours=2),
                            trigger="cron",
                            status="failed",
                            error="SMTP timeout",
                            finished_at=NOW - timedelta(hours=2),
                            created_at=NOW - timedelta(hours=2),
                        ),
                    ]
                )
                await session.commit()

            resp = await client.get("/api/briefs/today", headers=auth_headers(USER_A))
        assert resp.status_code == 200
        data = resp.json()
        by_kind = {}
        for item in data["activity"]:
            by_kind.setdefault(item["kind"], []).append(item)

        assert by_kind["run_success"][0]["thread_id"] == "t1"
        assert by_kind["run_failed"][0]["detail"].startswith("Boom")
        assert by_kind["document"][0]["title"] == "brief.pdf"
        assert "gone.pdf" not in {i["title"] for i in by_kind.get("document", [])}
        assert by_kind["scheduled_task_failed"][0]["title"] == "Weekly digest"
        assert by_kind["scheduled_task_failed"][0]["detail"] == "SMTP timeout"

        # Newest first.
        occurred = [item["occurred_at"] for item in data["activity"]]
        assert occurred == sorted(occurred, reverse=True)


class TestDueToday:
    async def test_only_todays_tasks_in_order(self, org_world, monkeypatch):  # noqa: F811
        session_factory = org_world
        client = _build_app(session_factory, monkeypatch)
        async with client:
            await _create_client_with_assignment(client, auth_headers(USER_A), "Acme")
            async with session_factory() as session:
                session.add_all(
                    [
                        _scheduled_task(id="due-late", title="Later today", next_run_at=NOW.replace(hour=20)),
                        _scheduled_task(id="due-early", title="Earlier today", next_run_at=NOW.replace(hour=6)),
                        _scheduled_task(id="due-tomorrow", title="Tomorrow", next_run_at=NOW + timedelta(days=1)),
                        _scheduled_task(id="due-paused", title="Paused today", status="paused", next_run_at=NOW.replace(hour=15)),
                    ]
                )
                await session.commit()
            resp = await client.get("/api/briefs/today", headers=auth_headers(USER_A))
        data = resp.json()
        assert [t["task_id"] for t in data["due_today"]] == ["due-early", "due-late"]

    async def test_tz_offset_shifts_the_local_day_window(self, org_world, monkeypatch):  # noqa: F811
        """A task at 23:00 UTC is "tomorrow" in UTC but still "today" for UTC-5."""
        session_factory = org_world
        client = _build_app(session_factory, monkeypatch)
        async with client:
            await _create_client_with_assignment(client, auth_headers(USER_A), "Acme")
            async with session_factory() as session:
                session.add(
                    ScheduledTaskRow(
                        id="due-late-utc",
                        user_id=USER_A,
                        organization_id=ORG_A,
                        title="Late UTC",
                        prompt="x",
                        schedule_type="cron",
                        timezone="UTC",
                        status="enabled",
                        next_run_at=NOW.replace(hour=23),
                        created_at=NOW,
                        updated_at=NOW,
                    )
                )
                await session.commit()

            resp_utc = await client.get("/api/briefs/today", headers=auth_headers(USER_A))
            resp_shifted = await client.get("/api/briefs/today", params={"tz_offset_minutes": -300}, headers=auth_headers(USER_A))
        assert [t["task_id"] for t in resp_utc.json()["due_today"]] == ["due-late-utc"]
        assert [t["task_id"] for t in resp_shifted.json()["due_today"]] == ["due-late-utc"]


class TestWaitingOnYou:
    async def test_interrupted_run_is_waiting(self, org_world, monkeypatch):  # noqa: F811
        session_factory = org_world
        client = _build_app(session_factory, monkeypatch)
        async with client:
            await _create_client_with_assignment(client, auth_headers(USER_A), "Acme")
            async with session_factory() as session:
                session.add_all(
                    [
                        _project(id="proj-1", name="Acme Website"),
                        _thread(thread_id="t1", project_id="proj-1", display_name="Blocked chat"),
                        _run(run_id="r1", thread_id="t1", status="interrupted", created_at=NOW - timedelta(hours=5), updated_at=NOW - timedelta(hours=5)),
                    ]
                )
                await session.commit()
            resp = await client.get("/api/briefs/today", headers=auth_headers(USER_A))
        [item] = resp.json()["waiting_on_you"]
        assert item["kind"] == "interrupted"
        assert item["thread_id"] == "t1"
        assert item["run_id"] == "r1"

    async def test_unanswered_clarification_is_waiting(self, org_world, monkeypatch):  # noqa: F811
        session_factory = org_world
        client = _build_app(session_factory, monkeypatch)
        async with client:
            await _create_client_with_assignment(client, auth_headers(USER_A), "Acme")
            async with session_factory() as session:
                session.add_all(
                    [
                        _project(id="proj-1", name="Acme Website"),
                        _thread(thread_id="t1", project_id="proj-1", display_name="Needs an answer"),
                        _run(run_id="r1", thread_id="t1", status="success", created_at=NOW - timedelta(hours=2), updated_at=NOW - timedelta(hours=2)),
                        RunEventRow(thread_id="t1", run_id="r1", user_id=USER_A, event_type="llm.human.input", category="message", content="{}", seq=1, created_at=NOW - timedelta(hours=2)),
                    ]
                )
                await session.commit()
            resp = await client.get("/api/briefs/today", headers=auth_headers(USER_A))
        [item] = resp.json()["waiting_on_you"]
        assert item["kind"] == "clarification"
        assert item["thread_id"] == "t1"

    async def test_only_the_latest_run_per_thread_counts(self, org_world, monkeypatch):  # noqa: F811
        """An interrupted run superseded by a normal follow-up run is no longer waiting."""
        session_factory = org_world
        client = _build_app(session_factory, monkeypatch)
        async with client:
            await _create_client_with_assignment(client, auth_headers(USER_A), "Acme")
            async with session_factory() as session:
                session.add_all(
                    [
                        _project(id="proj-1", name="Acme Website"),
                        _thread(thread_id="t1", project_id="proj-1", display_name="Resolved chat"),
                        _run(run_id="r-old", thread_id="t1", status="interrupted", created_at=NOW - timedelta(hours=5), updated_at=NOW - timedelta(hours=5)),
                        _run(run_id="r-new", thread_id="t1", status="success", created_at=NOW - timedelta(hours=1), updated_at=NOW - timedelta(hours=1)),
                    ]
                )
                await session.commit()
            resp = await client.get("/api/briefs/today", headers=auth_headers(USER_A))
        assert resp.json()["waiting_on_you"] == []

    async def test_waiting_ordered_oldest_first(self, org_world, monkeypatch):  # noqa: F811
        session_factory = org_world
        client = _build_app(session_factory, monkeypatch)
        async with client:
            await _create_client_with_assignment(client, auth_headers(USER_A), "Acme")
            async with session_factory() as session:
                session.add_all(
                    [
                        _project(id="proj-1", name="Acme Website"),
                        _thread(thread_id="t-newer", project_id="proj-1", display_name="Newer stall"),
                        _run(run_id="r-newer", thread_id="t-newer", status="interrupted", created_at=NOW - timedelta(hours=1), updated_at=NOW - timedelta(hours=1)),
                        _thread(thread_id="t-older", project_id="proj-1", display_name="Older stall"),
                        _run(run_id="r-older", thread_id="t-older", status="interrupted", created_at=NOW - timedelta(hours=8), updated_at=NOW - timedelta(hours=8)),
                    ]
                )
                await session.commit()
            resp = await client.get("/api/briefs/today", headers=auth_headers(USER_A))
        thread_order = [item["thread_id"] for item in resp.json()["waiting_on_you"]]
        assert thread_order == ["t-older", "t-newer"]


class TestCrossUserIsolationInSharedWorkspace:
    async def test_assigned_clients_are_actor_scoped_not_workspace_shared(self, org_world, monkeypatch):  # noqa: F811
        """a and c share workspace S; only a is assigned to the client a created."""
        session_factory = org_world
        client = _build_app(session_factory, monkeypatch)
        async with client:
            client_id = await _create_client_with_assignment(client, auth_headers(USER_A, ORG_S), "S client")
            resp_a = await client.get("/api/briefs/today", headers=auth_headers(USER_A, ORG_S))
            resp_c = await client.get("/api/briefs/today", headers=auth_headers(USER_C, ORG_S))
        assert [c["id"] for c in resp_a.json()["assigned_clients"]] == [client_id]
        assert resp_c.json()["assigned_clients"] == []


class TestNoSqlBackend:
    async def test_503_when_memory_backend(self, org_world, monkeypatch):  # noqa: F811
        monkeypatch.setattr(briefs, "get_session_factory", lambda: None)
        from fastapi import FastAPI

        app = FastAPI()
        app.add_middleware(AuthMiddleware)
        app.include_router(briefs.router)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/briefs/today", headers=auth_headers(USER_A))
        assert resp.status_code == 503
        assert "SQL database backend" in resp.json()["detail"]
