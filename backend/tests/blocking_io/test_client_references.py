"""Strict off-loop anchor for approved original reference bytes and metadata."""

import asyncio
import hashlib
from types import SimpleNamespace

import pytest

from app.gateway.routers import client_references
from deerflow.config.paths import Paths
from deerflow.projects.documents import resolve_document_paths


@pytest.mark.asyncio
async def test_reference_hash_read_and_download_do_not_block(tmp_path, monkeypatch):
    data = b"Approved original reference"
    sha = hashlib.sha256(data).hexdigest()
    paths = await asyncio.to_thread(Paths, base_dir=tmp_path)
    row = {"id": "doc", "project_id": "project", "name": "reference.txt", "sha256": sha, "size_bytes": len(data), "stored_relpath": f"project/documents/{sha[:2]}/{sha}/doc", "trashed_at": None}
    original, _ = await asyncio.to_thread(resolve_document_paths, paths, user_id="storage", relpath=row["stored_relpath"], name=row["name"])
    await asyncio.to_thread(original.parent.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread(original.write_bytes, data)

    class Projects:
        async def get(self, project_id, *, user_id):
            assert project_id == "project" and user_id == "storage"
            return {"id": "project", "name": "Reference", "status": "active"}

    class Documents:
        async def get(self, document_id, *, user_id):
            assert document_id == "doc" and user_id == "storage"
            return row

    monkeypatch.setattr(client_references, "get_paths", lambda: paths)
    monkeypatch.setattr(client_references, "get_project_repo", lambda request: Projects())
    monkeypatch.setattr(client_references, "get_project_document_repo", lambda request: Documents())
    scope = ("storage", {"project": {"doc": sha}})
    listing = await client_references.list_reference_documents("project", SimpleNamespace(), scope=scope)
    assert listing["documents"][0]["content_missing"] is False
    response = await client_references.get_reference_content("project", "doc", SimpleNamespace(), scope=scope)
    assert response.body == data
    assert response.headers["content-disposition"].startswith("attachment;")
