"""M3 lane B: organization isolation for threads, runs, artifacts, uploads, streams and the console.

A probe from another organization answers 404 (or is left out of a list), never 403 and
never data, and it changes nothing. Ownerless (``user_id`` NULL) and row-less threads fail
closed; the one row-less path left open is upload-before-create, which writes only into the
caller's own storage bucket. Internal callers act only through a delegation: a delegated
internal caller is held to the same boundaries, and a header-only one is refused outright.
"""

from __future__ import annotations

import asyncio
import hashlib
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from org_isolation_fixtures import ORG_A, ORG_B, ORG_S, STORAGE_S, USER_A, USER_B, USER_C, acting_as, auth_headers, org_world  # noqa: F401
from sqlalchemy import select, update

from app.gateway import services
from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.authz import _ALL_PERMISSIONS as ALL_ROUTE_PERMISSIONS
from app.gateway.internal_auth import create_internal_auth_headers
from app.gateway.routers import artifacts, browser, console, runs, thread_runs, threads, uploads
from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config
from deerflow.config.paths import Paths
from deerflow.persistence.feedback import FeedbackRepository
from deerflow.persistence.organizations.delegation import OrganizationDelegationRepository
from deerflow.persistence.organizations.model import OrganizationMemberRow
from deerflow.persistence.organizations.resolution import OrganizationMismatchError
from deerflow.persistence.run import RunRepository, RunRow
from deerflow.persistence.thread_meta import ThreadMetaRepository, ThreadMetaRow
from deerflow.runtime import MemoryStreamBridge, RunManager, RunStatus
from deerflow.runtime.events.store.db import DbRunEventStore

T_A, T_B, T_S = "thread-a", "thread-b", "thread-s"
R_A, R_B, R_S = "run-a", "run-b", "run-s"
T_NULL, T_ORPHAN = "thread-ownerless", "thread-orphan"
REPORT = "mnt/user-data/outputs/report.txt"
RUN_BODY = {"assistant_id": "lead_agent", "input": {"messages": [{"role": "user", "content": "hi"}]}}
SEEDED = ((USER_A, None, T_A, R_A, 100), (USER_B, None, T_B, R_B, 200), (USER_C, ORG_S, T_S, R_S, 300))


def _broken_agent_factory(*_args, **_kwargs):
    # No model in these tests: full-mode reads degrade to raw checkpoint values.
    raise RuntimeError("no agent in organization isolation tests")


async def _finish_run(bridge, run_manager, record, **_kwargs):
    await run_manager.set_status(record.run_id, RunStatus.success)
    await bridge.publish_end(record.run_id)


async def _put_checkpoint(saver: InMemorySaver, thread_id: str, run_id: str | None = None) -> None:
    messages = [
        HumanMessage(id=f"h-{thread_id}", content=f"question {thread_id}", additional_kwargs={"run_id": run_id} if run_id else {}),
        AIMessage(id=f"a-{thread_id}", content=f"answer {thread_id}"),
    ]
    checkpoint = empty_checkpoint()
    checkpoint["channel_values"] = {"messages": messages, "title": thread_id}
    checkpoint["channel_versions"] = {"messages": 1, "title": 1}
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    await saver.aput(config, checkpoint, {"step": 1, "source": "loop", "writes": {}, "parents": {}}, {"messages": 1, "title": 1})


class World:
    """A real Gateway surface (AuthMiddleware plus the lane B routers) over ``org_world``."""

    def __init__(self, session_factory, root, app: FastAPI):
        self.sf = session_factory
        self.root = root
        self.paths = Paths(root)
        self.app = app
        state = app.state
        self.threads: ThreadMetaRepository = state.thread_store
        self.runs: RunRepository = state.run_store
        self.events: DbRunEventStore = state.run_event_store
        self.checkpointer: InMemorySaver = state.checkpointer
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test")

    async def request(self, actor, method, path, body=None, *, org=None, headers=None):
        kwargs = {"files": body["files"]} if isinstance(body, dict) and "files" in body else {"json": body}
        return await self.client.request(method, path, headers=headers if headers is not None else auth_headers(actor, org), **kwargs)

    def outputs(self, thread_id: str, storage_user: str):
        return self.paths.sandbox_outputs_dir(thread_id, user_id=storage_user)

    async def snapshot(self):
        """Everything a probe could change: rows, checkpoints and files on disk."""
        async with self.sf() as session:
            thread_rows = (await session.execute(select(ThreadMetaRow).order_by(ThreadMetaRow.thread_id))).scalars().all()
            run_rows = (await session.execute(select(RunRow).order_by(RunRow.run_id))).scalars().all()
            rows = [(row.thread_id, row.user_id, row.organization_id, row.display_name, row.metadata_json, row.status, row.project_id) for row in thread_rows]
            rows += [(row.run_id, row.thread_id, row.user_id, row.organization_id, row.status, row.operation_kind) for row in run_rows]
        checkpoints = {thread_id: sorted(checkpoint_id for namespace in by_ns.values() for checkpoint_id in namespace) for thread_id, by_ns in self.checkpointer.storage.items()}
        files = sorted((str(path.relative_to(self.root)), path.read_bytes()) for path in self.root.rglob("*") if path.is_file())
        return rows, checkpoints, files


@pytest_asyncio.fixture()
async def world(org_world, tmp_path, monkeypatch):  # noqa: F811
    # Shared-workspace runs require the isolated AIO sandbox; no test here starts one.
    set_app_config(AppConfig.model_validate({"sandbox": {"use": "deerflow.community.aio_sandbox:AioSandboxProvider", "network": {"mode": "isolated"}}}))
    monkeypatch.setattr("deerflow.config.paths._paths", Paths(tmp_path))
    monkeypatch.setattr(console, "get_session_factory", lambda: org_world)  # bound at import, unlike org_world's patch
    monkeypatch.setattr(services, "resolve_agent_factory", lambda *_args: _broken_agent_factory)
    monkeypatch.setattr(services, "run_agent", _finish_run)
    mounted = SimpleNamespace(uses_thread_data_mounts=True)
    monkeypatch.setattr(uploads, "get_sandbox_provider", lambda: mounted)
    monkeypatch.setattr(artifacts, "get_sandbox_provider", lambda: mounted)

    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    for router in (threads.router, thread_runs.router, runs.router, artifacts.router, uploads.router, console.router, browser.router):
        app.include_router(router)
    state = app.state
    state.thread_store = ThreadMetaRepository(org_world)
    state.run_store = RunRepository(org_world)
    state.run_event_store = DbRunEventStore(org_world)
    state.run_manager = RunManager(store=state.run_store, event_store=state.run_event_store)
    state.feedback_repo = FeedbackRepository(org_world)
    state.checkpointer = InMemorySaver()
    state.store = InMemoryStore()
    state.stream_bridge = MemoryStreamBridge()
    state.checkpoint_channel_mode = "full"
    state.run_events_config = None
    w = World(org_world, tmp_path, app)
    # A fully scoped internal worker acting for a in org A: delegated, not header-only.
    worker = await OrganizationDelegationRepository(org_world).grant(organization_id=ORG_A, subject_type="test_worker", subject_id="worker-a", owner_user_id=USER_A, scopes=sorted(ALL_ROUTE_PERMISSIONS))
    w.delegated_a = create_internal_auth_headers(owner_user_id=USER_A, delegation_id=worker)

    for actor, org, thread_id, run_id, tokens in SEEDED:
        with acting_as(actor, org):
            await w.threads.create(thread_id, assistant_id="lead_agent", display_name=thread_id)
            await w.runs.put(run_id, thread_id=thread_id, assistant_id="lead_agent", status="running")
            await w.runs.update_run_completion(run_id, status="success", total_tokens=tokens, total_input_tokens=tokens, message_count=2)
            answer = AIMessage(id=f"a-{thread_id}", content=f"answer {thread_id}").model_dump()
            await w.events.put(thread_id=thread_id, run_id=run_id, event_type="llm.ai.response", category="message", content=answer, metadata={"usage": {"input_tokens": tokens, "total_tokens": tokens}})
        await _put_checkpoint(w.checkpointer, thread_id, run_id)
        storage = STORAGE_S if org == ORG_S else actor
        w.outputs(thread_id, storage).mkdir(parents=True)
        (w.outputs(thread_id, storage) / "report.txt").write_text(f"report for {thread_id}")
        uploads_dir = w.paths.sandbox_uploads_dir(thread_id, user_id=storage)
        uploads_dir.mkdir(parents=True)
        (uploads_dir / "note.txt").write_text(f"note for {thread_id}")
    # Legacy data the decision in force hides from everyone: an ownerless row and a
    # checkpoint that no row owns (both carry someone's conversation).
    await w.threads.create(T_NULL, user_id=None)
    await _put_checkpoint(w.checkpointer, T_NULL)
    await _put_checkpoint(w.checkpointer, T_ORPHAN)

    try:
        yield w
    finally:
        await w.client.aclose()
        pending = [record.task for record in state.run_manager._runs.values() if record.task is not None]
        await asyncio.gather(*pending, return_exceptions=True)
        reset_app_config()


def _report_sha(thread_id: str) -> str:
    return hashlib.sha256(f"report for {thread_id}".encode()).hexdigest()


# (method, path, body). ``{t}`` and ``{r}`` are filled with the target thread and run.
PROBES = [
    ("GET", "/api/threads/{t}", None),
    ("PATCH", "/api/threads/{t}", {"metadata": {"probe": True}}),
    ("DELETE", "/api/threads/{t}", None),
    ("POST", "/api/threads/{t}/move", {"project_id": None}),
    ("POST", "/api/threads/{t}/branches", {"message_id": "a-{t}"}),
    ("GET", "/api/threads/{t}/state", None),
    ("POST", "/api/threads/{t}/state", {"values": {"title": "probe"}}),
    ("POST", "/api/threads/{t}/history", {}),
    ("GET", "/api/threads/{t}/goal", None),
    ("PUT", "/api/threads/{t}/goal", {"objective": "probe"}),
    ("DELETE", "/api/threads/{t}/goal", None),
    ("POST", "/api/threads/{t}/compact", {}),
    ("GET", "/api/threads/{t}/token-usage", None),
    ("POST", "/api/threads/{t}/runs", RUN_BODY),
    ("POST", "/api/threads/{t}/runs/stream", RUN_BODY),
    ("POST", "/api/threads/{t}/runs/wait", RUN_BODY),
    ("POST", "/api/threads/{t}/runs/regenerate/prepare", {"message_id": "a-{t}"}),
    ("POST", "/api/threads/{t}/runs/edit-regenerate/prepare", {"human_message_id": "h-{t}", "replacement_text": "edited"}),
    ("GET", "/api/threads/{t}/runs", None),
    ("GET", "/api/threads/{t}/runs/page", None),
    ("GET", "/api/threads/{t}/runs/{r}", None),
    ("POST", "/api/threads/{t}/runs/{r}/cancel", None),
    ("GET", "/api/threads/{t}/runs/{r}/join", None),
    ("GET", "/api/threads/{t}/runs/{r}/stream", None),
    ("POST", "/api/threads/{t}/runs/{r}/stream", None),
    ("GET", "/api/threads/{t}/messages", None),
    ("GET", "/api/threads/{t}/messages/page", None),
    ("GET", "/api/threads/{t}/runs/{r}/messages", None),
    ("GET", "/api/threads/{t}/runs/{r}/events", None),
    ("GET", "/api/threads/{t}/runs/{r}/workspace-changes", None),
    ("GET", "/api/threads/{t}/runs/{r}/artifacts/archive", None),
    ("POST", "/api/threads/{t}/runs/{r}/artifacts/archive", None),
    ("GET", f"/api/threads/{{t}}/artifacts/{REPORT}", None),
    ("PUT", f"/api/threads/{{t}}/artifacts/{REPORT}", {"content": "overwritten", "expected_sha256": "{sha}"}),
    ("POST", "/api/threads/{t}/uploads", {"files": {"files": ("probe.txt", b"probe")}}),
    ("GET", "/api/threads/{t}/uploads/list", None),
    ("GET", "/api/threads/{t}/uploads/limits", None),
    ("DELETE", "/api/threads/{t}/uploads/note.txt", None),
    ("POST", "/api/threads/{t}/browser/navigate", {"url": "https://example.com"}),
    ("POST", "/api/runs/stream", {**RUN_BODY, "config": {"configurable": {"thread_id": "{t}"}}}),
    ("POST", "/api/runs/wait", {**RUN_BODY, "config": {"configurable": {"thread_id": "{t}"}}}),
    ("GET", "/api/runs/{r}/messages", None),
    ("GET", "/api/runs/{r}/feedback", None),
]


def _fill(value, thread_id: str, run_id: str):
    if isinstance(value, str):
        return value.replace("{t}", thread_id).replace("{r}", run_id).replace("{sha}", _report_sha(thread_id))
    if isinstance(value, dict) and "files" not in value:
        return {key: _fill(item, thread_id, run_id) for key, item in value.items()}
    return value


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "path", "body"), PROBES, ids=[f"{method} {path}" for method, path, _ in PROBES])
async def test_cross_organization_probe_is_404_and_changes_nothing(world, method, path, body):
    target, payload = _fill(path, T_A, R_A), _fill(body, T_A, R_A)
    before = await world.snapshot()
    # b in its own organization, c and a in the shared workspace: a's private thread is
    # not theirs, and switching a into S hides it from a as well.
    for actor, org in ((USER_B, None), (USER_C, ORG_S), (USER_A, ORG_S)):
        response = await world.request(actor, method, target, payload, org=org)
        assert response.status_code == 404, (actor, org, response.status_code, response.text)
        assert "answer thread-a" not in response.text and "report for thread-a" not in response.text
    assert await world.snapshot() == before
    if "/browser/" in path:
        return  # the owner's navigate would start a real browser; its strict owner check has its own suite
    owner = await world.request(USER_A, method, target, payload)
    assert owner.status_code != 404, (owner.status_code, owner.text)


THREAD_ROUTES = [(method, path, body) for method, path, body in PROBES if path.startswith("/api/threads/{t}") and "/uploads" not in path and "/browser/" not in path]


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "path", "body"), THREAD_ROUTES, ids=[f"{method} {path}" for method, path, _ in THREAD_ROUTES])
async def test_ownerless_and_orphan_threads_fail_closed_for_everyone(world, method, path, body):
    before = await world.snapshot()
    internal = world.delegated_a
    for thread_id in (T_NULL, T_ORPHAN):
        target, payload = _fill(path, thread_id, R_A), _fill(body, thread_id, R_A)
        for actor, headers in ((USER_A, None), (USER_B, None), (None, internal)):
            response = await world.request(actor, method, target, payload, headers=headers)
            assert response.status_code == 404, (thread_id, actor, response.status_code, response.text)
            assert f"answer {thread_id}" not in response.text
    assert await world.snapshot() == before


@pytest.mark.asyncio
async def test_create_and_goal_cannot_claim_an_existing_checkpoint_or_row(world):
    before = await world.snapshot()
    internal = world.delegated_a
    for thread_id in (T_NULL, T_ORPHAN, T_B):
        for headers in (auth_headers(USER_A), internal):
            created = await world.request(None, "POST", "/api/threads", {"thread_id": thread_id}, headers=headers)
            assert created.status_code == 404, (thread_id, created.status_code, created.text)
            goal = await world.request(None, "PUT", f"/api/threads/{thread_id}/goal", {"objective": "claim"}, headers=headers)
            assert goal.status_code == 404, (thread_id, goal.status_code, goal.text)
    # Upload-before-create does not extend to an existing ownerless row.
    for method, path, body in [probe for probe in PROBES if "/uploads" in probe[1]]:
        assert (await world.request(USER_A, method, _fill(path, T_NULL, R_A), body)).status_code == 404, path
    assert await world.snapshot() == before
    assert (await world.threads.get(T_NULL, user_id=None))["user_id"] is None
    assert await world.threads.get(T_ORPHAN, user_id=None) is None


@pytest.mark.asyncio
async def test_unused_ids_still_create_in_the_active_organization(world):
    fresh = await world.request(USER_A, "PUT", "/api/threads/thread-goal-first/goal", {"objective": "ship it"})
    assert fresh.status_code == 200, fresh.text
    created = await world.request(USER_C, "POST", "/api/threads", {"thread_id": "thread-new-in-s"}, org=ORG_S)
    assert created.status_code == 200, created.text
    again = await world.request(USER_A, "POST", "/api/threads", {"thread_id": "thread-new-in-s"}, org=ORG_S)
    assert again.status_code == 200, again.text  # idempotent for every member of S
    rows = {row["thread_id"]: row for row in await world.threads.search(user_id=None)}
    assert (rows["thread-goal-first"]["user_id"], rows["thread-goal-first"]["organization_id"]) == (USER_A, ORG_A)
    assert (rows["thread-new-in-s"]["user_id"], rows["thread-new-in-s"]["organization_id"]) == (STORAGE_S, ORG_S)
    assert (await world.request(USER_B, "POST", "/api/threads", {"thread_id": "thread-new-in-s"})).status_code == 404


@pytest.mark.asyncio
async def test_switching_active_organization_flips_visibility(world):
    async def visible(actor, org=None):
        response = await world.request(actor, "POST", "/api/threads/search", {}, org=org)
        assert response.status_code == 200, response.text
        return {row["thread_id"] for row in response.json()}

    assert await visible(USER_A) == {T_A}
    assert await visible(USER_A, ORG_S) == {T_S}
    assert await visible(USER_C, ORG_S) == {T_S}
    assert await visible(USER_B) == {T_B}
    assert (await world.request(USER_A, "GET", f"/api/threads/{T_S}")).status_code == 404
    assert (await world.request(USER_A, "GET", f"/api/threads/{T_S}", org=ORG_S)).status_code == 200
    assert (await world.request(USER_C, "GET", f"/api/threads/{T_S}/runs/{R_S}", org=ORG_S)).status_code == 200
    assert (await world.request(USER_A, "GET", f"/api/threads/{T_A}/runs/{R_A}", org=ORG_S)).status_code == 404


@pytest.mark.asyncio
async def test_artifact_and_upload_files_stay_in_the_storage_principals_bucket(world):
    # A file for a's thread planted in b's bucket is never served to anyone: a reads its own
    # bucket, and b cannot address a's thread at all.
    planted = world.outputs(T_A, USER_B)
    planted.mkdir(parents=True)
    (planted / "planted.txt").write_text("b bucket")
    assert (await world.request(USER_A, "GET", f"/api/threads/{T_A}/artifacts/mnt/user-data/outputs/planted.txt")).status_code == 404
    own = await world.request(USER_A, "GET", f"/api/threads/{T_A}/artifacts/{REPORT}")
    assert (own.status_code, own.text) == (200, "report for thread-a")
    shared = await world.request(USER_C, "GET", f"/api/threads/{T_S}/artifacts/{REPORT}", org=ORG_S)
    assert (shared.status_code, shared.text) == (200, "report for thread-s")

    # Upload-before-create writes into the caller's bucket only, and another caller's listing
    # of the same unused id is their own (empty) bucket.
    uploaded = await world.request(USER_A, "POST", "/api/threads/thread-unborn/uploads", {"files": {"files": ("draft.txt", b"a draft")}})
    assert uploaded.status_code == 200, uploaded.text
    assert (world.paths.sandbox_uploads_dir("thread-unborn", user_id=USER_A) / "draft.txt").read_bytes() == b"a draft"
    listing = await world.request(USER_B, "GET", "/api/threads/thread-unborn/uploads/list")
    assert (listing.status_code, listing.json()["files"]) == (200, [])
    assert not world.paths.thread_dir("thread-unborn", user_id=USER_B).exists()


@pytest.mark.asyncio
async def test_console_totals_count_only_the_active_organization(world):
    # A legacy run with no organization is quarantined: it does not count for its user either.
    with acting_as(USER_A):
        await world.runs.put("run-a-legacy", thread_id=T_A, status="success", user_id=USER_A)
    async with world.sf() as session, session.begin():
        await session.execute(update(RunRow).where(RunRow.run_id == "run-a-legacy").values(organization_id=None, total_tokens=5000))

    async def console(actor, org=None):
        responses = {}
        for name in ("stats", "runs", "usage", "usage-ledger"):
            response = await world.request(actor, "GET", f"/api/console/{name}", org=org)
            assert response.status_code == 200, response.text
            responses[name] = response.json()
        return responses

    for actor, org, run_id, tokens in ((USER_A, None, R_A, 100), (USER_B, None, R_B, 200), (USER_A, ORG_S, R_S, 300), (USER_C, ORG_S, R_S, 300)):
        seen = await console(actor, org)
        assert (seen["stats"]["total_runs"], seen["stats"]["total_threads"], seen["stats"]["total_tokens"]) == (1, 1, tokens), (actor, org, seen["stats"])
        assert [item["run_id"] for item in seen["runs"]["runs"]] == [run_id]
        assert (seen["usage"]["total_runs"], seen["usage"]["total_tokens"]) == (1, tokens)
        assert {item["run_id"] for item in seen["usage-ledger"]["attempts"]} == {run_id}


@pytest.mark.asyncio
async def test_organization_filter_stands_beside_the_user_filter(world):
    # The user filter alone would show these rows to user a; the missing organization
    # (the quarantine marker) hides them whenever an active organization is established.
    await world.threads.create("thread-a-quarantine", user_id=USER_A)
    with acting_as(USER_A):
        await world.runs.put("run-a-quarantine", thread_id="thread-a-quarantine", status="success")
    async with world.sf() as session, session.begin():
        await session.execute(update(ThreadMetaRow).where(ThreadMetaRow.thread_id == "thread-a-quarantine").values(organization_id=None))
        await session.execute(update(RunRow).where(RunRow.run_id == "run-a-quarantine").values(organization_id=None))

    with acting_as(USER_A):
        assert await world.threads.get("thread-a-quarantine") is None
        assert await world.threads.check_access("thread-a-quarantine", USER_A) is False
        assert "thread-a-quarantine" not in {row["thread_id"] for row in await world.threads.search()}
        await world.threads.update_metadata("thread-a-quarantine", {"touched": True})
        assert await world.runs.get("run-a-quarantine") is None
        assert [row["run_id"] for row in await world.runs.list_by_thread("thread-a-quarantine")] == []
        # Cross-organization rows stay invisible even through an explicit user bypass.
        assert await world.threads.get(T_B, user_id=None) is None
        assert await world.runs.get(R_B, user_id=None) is None
    # Without an organization boundary (internal callers, migrations) the user filter alone applies.
    row = await world.threads.get("thread-a-quarantine", user_id=USER_A)
    assert row is not None and "touched" not in row["metadata"]
    assert (await world.runs.get("run-a-quarantine", user_id=USER_A)) is not None
    # Ownerless rows fail closed for every caller, with or without an organization.
    assert await world.threads.check_access(T_NULL, USER_A) is False
    assert await world.threads.check_access(T_NULL, USER_A, require_existing=True) is False


@pytest.mark.asyncio
async def test_runs_are_stamped_with_the_server_resolved_organization(world):
    # Stateless runs are admitted before their thread row exists; they still get an organization.
    with acting_as(USER_A):
        await world.runs.create_thread_operation_atomic("run-stateless", thread_id="thread-unborn", owner_worker_id="w", lease_expires_at=None)
        await world.runs.put("run-put-stateless", thread_id="thread-unborn-2")
    with acting_as(USER_C, ORG_S):
        await world.runs.create_thread_operation_atomic("run-stateless-s", thread_id="thread-unborn-s", owner_worker_id="w", lease_expires_at=None)
    stamped = {run_id: (row["user_id"], row["organization_id"]) for run_id in ("run-stateless", "run-put-stateless", "run-stateless-s") if (row := await world.runs.get(run_id, user_id=None))}
    assert stamped == {"run-stateless": (USER_A, ORG_A), "run-put-stateless": (USER_A, ORG_A), "run-stateless-s": (STORAGE_S, ORG_S)}
    # A storage principal that is not the active organization's is refused, never guessed.
    with acting_as(USER_A), pytest.raises(OrganizationMismatchError):
        await world.runs.put("run-mixed", thread_id="thread-unborn-3", user_id=USER_B)

    # Through HTTP: a stateless run with no thread lands in the caller's organization.
    response = await world.request(USER_A, "POST", "/api/runs/wait", RUN_BODY)
    assert response.status_code == 200, response.text
    async with world.sf() as session:
        created = (await session.execute(select(RunRow.user_id, RunRow.organization_id).where(RunRow.operation_kind == "run", RunRow.run_id.not_in([R_A, R_B, R_S, "run-stateless", "run-put-stateless", "run-stateless-s"])))).all()
    assert [tuple(row) for row in created] == [(USER_A, ORG_A)]


# ---------------------------------------------------------------------------
# Lane 0 phase 2: run admission, seeding, stream revocation and the internal owner header.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stateless_run_cannot_claim_an_orphan_checkpoint(world):
    """services.start_run admits a missing row, then _ensure_thread_metadata creates ownership over the checkpoint."""
    response = await world.request(USER_A, "POST", "/api/runs/wait", {**RUN_BODY, "config": {"configurable": {"thread_id": T_ORPHAN}}})
    assert response.status_code == 404, response.text
    assert "answer thread-orphan" not in response.text
    assert await world.threads.get(T_ORPHAN, user_id=None) is None


@pytest.mark.asyncio
async def test_checkpoint_history_is_not_seeded_from_an_unowned_checkpoint(world):
    """services.ensure_checkpoint_history_seeded copies any thread's checkpoint messages into the caller's feed."""
    request = SimpleNamespace(app=world.app, headers={}, state=SimpleNamespace())
    with acting_as(USER_A):
        await world.threads.create("thread-a-legacy-feed")
    await _put_checkpoint(world.checkpointer, "thread-a-legacy-feed")
    with acting_as(USER_A):
        await services.ensure_checkpoint_history_seeded(request, thread_id="thread-a-legacy-feed", assistant_id=None)
        await services.ensure_checkpoint_history_seeded(request, thread_id=T_ORPHAN, assistant_id=None)
    assert len(await world.events.list_messages("thread-a-legacy-feed", user_id=None)) == 2  # the owner's own legacy thread still seeds
    assert await world.events.list_messages(T_ORPHAN, user_id=None) == []


@pytest.mark.asyncio
async def test_open_stream_closes_when_membership_is_revoked(world):
    """services.sse_consumer checks admission once; revoking the viewer's membership must end the stream."""
    bridge = MemoryStreamBridge(heartbeat_interval=0.02)
    record = SimpleNamespace(run_id="run-live", status=RunStatus.running, store_only=False, user_id=STORAGE_S)

    async def never_disconnected():
        return False

    request = SimpleNamespace(
        headers={},
        is_disconnected=never_disconnected,
        state=SimpleNamespace(user=SimpleNamespace(id=USER_C), actor_user_id=USER_C, organization_id=ORG_S, storage_user_id=STORAGE_S, auth_source="session"),
        app=world.app,
    )
    frames = []

    async def watch():
        with acting_as(USER_C, ORG_S):
            async for frame in services.sse_consumer(bridge, record, request, world.app.state.run_manager, apply_on_disconnect=False):
                frames.append(frame)
                if len(frames) == 2:
                    async with world.sf() as session, session.begin():
                        await session.execute(update(OrganizationMemberRow).where(OrganizationMemberRow.organization_id == ORG_S, OrganizationMemberRow.user_id == USER_C).values(status="revoked"))

    await asyncio.wait_for(watch(), timeout=2)


@pytest.mark.asyncio
async def test_internal_owner_header_alone_cannot_read_another_bucket(world):
    """artifacts.py resolves the storage bucket from X-DeerFlow-Owner-User-Id; with no delegation that must fail closed."""
    response = await world.request(None, "GET", f"/api/threads/{T_B}/artifacts/{REPORT}", headers=create_internal_auth_headers(owner_user_id=USER_B))
    assert response.status_code in (401, 403, 404), response.text
    assert "report for thread-b" not in response.text
