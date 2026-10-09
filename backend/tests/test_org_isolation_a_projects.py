"""M3 lane A: organization isolation for projects and project documents.

Drives the real routers (``projects``, ``project_documents``,
``project_thread_files``, ``trash``) behind the real ``AuthMiddleware`` and
the shared ``org_isolation_fixtures`` world, so every check exercises the
same server-resolved organization context production requests get.

Covers:
    - every project/document/trash route 404s across private organizations
      (org A prober against org B's data), including list-excludes;
    - a co-member of shared workspace S sees S's projects;
    - switching the caller's active organization flips project visibility;
    - restoring a trashed document re-derives and stamps the organization
      from the TARGET project instead of leaving a stale/NULL value
      (``ProjectDocumentRepository.restore``, sql.py ~655).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import FastAPI
from org_isolation_fixtures import ORG_A, ORG_S, STORAGE_S, USER_A, USER_B, USER_C, acting_as, auth_headers, org_world  # noqa: F401

from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.deps import get_config
from app.gateway.routers import project_documents, project_thread_files, projects, trash
from deerflow.persistence.projects import ProjectDocumentRepository, ProjectRepository
from deerflow.persistence.projects.model import ProjectDocumentRow
from deerflow.persistence.thread_meta import ThreadMetaRepository


def _build_app(session_factory) -> FastAPI:
    """Real ``AuthMiddleware`` + every lane-A router on the shared test DB."""
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.state.project_repo = ProjectRepository(session_factory)
    app.state.project_document_repo = ProjectDocumentRepository(session_factory)
    app.state.thread_store = ThreadMetaRepository(session_factory)
    app.include_router(projects.router)
    app.include_router(project_documents.router)
    app.include_router(project_thread_files.router)
    app.include_router(trash.router)

    cfg = MagicMock()
    cfg.uploads = {}
    app.dependency_overrides[get_config] = lambda: cfg
    return app


@pytest.fixture(autouse=True)
def _isolate_paths(tmp_path, monkeypatch):
    """Give every test its own filesystem root (upload/content-download routes)."""
    import deerflow.config.paths as paths_mod

    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(paths_mod, "_paths", None)
    yield


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _create_project(client: httpx.AsyncClient, headers: dict[str, str], name: str = "p") -> dict[str, Any]:
    response = await client.post("/api/projects", json={"name": name}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


async def _upload_document(client: httpx.AsyncClient, project_id: str, headers: dict[str, str], filename: str = "note.txt", data: bytes = b"hello") -> dict[str, Any]:
    response = await client.post(f"/api/projects/{project_id}/documents", files={"file": (filename, data)}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["document"]


async def _create_thread(session_factory, *, actor: str, thread_id: str) -> None:
    store = ThreadMetaRepository(session_factory)
    with acting_as(actor):
        await store.create(thread_id)


# ---------------------------------------------------------------------------
# Cross-organization 404 sweep (org A prober vs org B's data)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_project_and_document_routes_404_across_organizations(org_world):  # noqa: F811
    session_factory = org_world
    app = _build_app(session_factory)
    headers_a = auth_headers(USER_A)
    headers_b = auth_headers(USER_B)

    async with _client(app) as client:
        # --- Seed everything as org A: a project, an active document, a
        # trashed document, and a thread A owns (for attach-to-thread).
        project_a = await _create_project(client, headers_a, "A's project")
        pid = project_a["id"]
        doc_a = await _upload_document(client, pid, headers_a, "keep.txt", b"keep me")
        trashed_source = await _upload_document(client, pid, headers_a, "trash-me.txt", b"bye")
        trashed = await client.delete(f"/api/projects/{pid}/documents/{trashed_source['id']}", headers=headers_a)
        assert trashed.status_code == 204
        await _create_thread(session_factory, actor=USER_B, thread_id="thread-b")

        # --- list excludes: B's project listing never contains A's project.
        listing = await client.get("/api/projects", headers=headers_b)
        assert listing.status_code == 200
        assert pid not in [p["id"] for p in listing.json()["projects"]]

        trash_listing = await client.get("/api/trash/documents", headers=headers_b)
        assert trash_listing.status_code == 200
        assert trashed_source["id"] not in [d["id"] for d in trash_listing.json()["documents"]]

        # --- get / patch / archive / restore / delete: a foreign project id
        # is indistinguishable from a missing one.
        assert (await client.get(f"/api/projects/{pid}", headers=headers_b)).status_code == 404
        assert (await client.patch(f"/api/projects/{pid}", json={"name": "hijacked"}, headers=headers_b)).status_code == 404
        assert (await client.post(f"/api/projects/{pid}/archive", headers=headers_b)).status_code == 404
        assert (await client.post(f"/api/projects/{pid}/restore", headers=headers_b)).status_code == 404
        assert (await client.get(f"/api/projects/{pid}/threads", headers=headers_b)).status_code == 404
        assert (await client.get(f"/api/projects/{pid}/thread-files", headers=headers_b)).status_code == 404

        # --- documents: list / upload / content / attach / delete.
        assert (await client.get(f"/api/projects/{pid}/documents", headers=headers_b)).status_code == 404
        upload_attempt = await client.post(f"/api/projects/{pid}/documents", files={"file": ("x.txt", b"x")}, headers=headers_b)
        assert upload_attempt.status_code == 404
        assert (await client.get(f"/api/projects/{pid}/documents/{doc_a['id']}/content", headers=headers_b)).status_code == 404
        attach_attempt = await client.post(f"/api/projects/{pid}/documents/{doc_a['id']}/attach-to-thread/thread-b", headers=headers_b)
        assert attach_attempt.status_code == 404
        assert (await client.delete(f"/api/projects/{pid}/documents/{doc_a['id']}", headers=headers_b)).status_code == 404

        # --- trash: restore / purge of a foreign trashed document.
        assert (await client.post(f"/api/trash/documents/{trashed_source['id']}/restore", headers=headers_b)).status_code == 404
        assert (await client.post(f"/api/trash/documents/{trashed_source['id']}/purge", headers=headers_b)).status_code == 404

        # --- delete last: confirm it is a true no-op, not just "already gone".
        assert (await client.delete(f"/api/projects/{pid}", headers=headers_b)).status_code == 404
        still_there = await client.get(f"/api/projects/{pid}", headers=headers_a)
        assert still_there.status_code == 200


# ---------------------------------------------------------------------------
# Shared workspace S: co-members see S's projects
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shared_workspace_co_member_sees_projects(org_world):  # noqa: F811
    session_factory = org_world
    app = _build_app(session_factory)

    async with _client(app) as client:
        project_s = await _create_project(client, auth_headers(USER_A, ORG_S), "S's project")

        # c is an active admin of S: sees and can open the project a created.
        as_c = auth_headers(USER_C, ORG_S)
        listing = await client.get("/api/projects", headers=as_c)
        assert listing.status_code == 200
        assert project_s["id"] in [p["id"] for p in listing.json()["projects"]]
        assert (await client.get(f"/api/projects/{project_s['id']}", headers=as_c)).status_code == 200

        # b has no membership in S at all: AuthMiddleware itself fails closed
        # before any project route is even reached.
        assert (await client.get("/api/projects", headers=auth_headers(USER_B, ORG_S))).status_code == 403


# ---------------------------------------------------------------------------
# Switching the active organization flips visibility
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_switching_active_organization_flips_visibility(org_world):  # noqa: F811
    session_factory = org_world
    app = _build_app(session_factory)

    async with _client(app) as client:
        # The same human (a) owns both org A and is a member of S.
        project_private = await _create_project(client, auth_headers(USER_A), "A private")
        project_shared = await _create_project(client, auth_headers(USER_A, ORG_S), "A in S")

        as_private = auth_headers(USER_A)
        as_shared = auth_headers(USER_A, ORG_S)

        private_ids = {p["id"] for p in (await client.get("/api/projects", headers=as_private)).json()["projects"]}
        assert private_ids == {project_private["id"]}

        shared_ids = {p["id"] for p in (await client.get("/api/projects", headers=as_shared)).json()["projects"]}
        assert shared_ids == {project_shared["id"]}

        # Same rule from the single-resource route.
        assert (await client.get(f"/api/projects/{project_shared['id']}", headers=as_private)).status_code == 404
        assert (await client.get(f"/api/projects/{project_private['id']}", headers=as_shared)).status_code == 404


# ---------------------------------------------------------------------------
# Restore re-derives and stamps the TARGET project's organization
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_restore_rederives_and_stamps_the_target_projects_organization(org_world):  # noqa: F811
    session_factory = org_world
    project_repo = ProjectRepository(session_factory)
    document_repo = ProjectDocumentRepository(session_factory)

    with acting_as(USER_A):
        source_project = await project_repo.create(name="source")
        target_project = await project_repo.create(name="target")
        inserted = await document_repo.insert_active(
            source_project["id"],
            document_id="doc-1",
            name="note.txt",
            relpath="doc-1/note.txt",
            sha256="a" * 64,
            size_bytes=3,
        )
        assert inserted["organization_id"] == ORG_A

        assert await document_repo.trash("doc-1", project_id=source_project["id"])

        # Simulate a legacy/quarantined row: NULL organization_id, exactly as
        # an unmigrated pre-0027 row would carry (state matrix: dual-write
        # only started at 0027). Corrupting it only AFTER trashing proves the
        # bug is in restore's re-point, not in trash's own scoping. user_id
        # (the actual ownership proof for this table) is untouched.
        async with session_factory() as session:
            row = await session.get(ProjectDocumentRow, "doc-1")
            row.organization_id = None
            await session.commit()

        outcome, restored = await document_repo.restore("doc-1", target_project_id=target_project["id"])
        assert outcome == "restored"
        assert restored is not None
        assert restored["organization_id"] == ORG_A, "restore must re-derive organization_id from the target project, not leave it stale/NULL"

        # The read path confirms the healing: a document stuck at NULL would
        # otherwise vanish once its row is read back.
        refetched = await document_repo.get("doc-1")
        assert refetched is not None
        assert refetched["organization_id"] == ORG_A
