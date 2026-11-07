"""Opt-in, hash-bound reference projection, independent of staff project access.

The operator explicitly approves an existing actor, active organization, project,
and immutable document digests. This grants no staff project permission, mutation,
thread/history access, model call, or account membership.
"""

import hashlib
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr, ValidationError

from app.gateway.authz import get_auth_context
from app.gateway.deps import get_config, get_project_document_repo, get_project_repo
from deerflow.config.paths import get_paths
from deerflow.projects.documents import resolve_document_paths
from deerflow.runtime.user_context import get_effective_user_id, resolve_organization_id
from deerflow.utils.file_io import run_file_io

router = APIRouter(prefix="/api/client-references", tags=["client-references"])
Identifier = Annotated[StrictStr, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")]
Digest = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
MAX_DOCUMENT_BYTES = 10 * 1024 * 1024


class ReferenceBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: Identifier
    organization_id: Identifier
    project_id: Identifier
    documents: Annotated[dict[Identifier, Digest], Field(min_length=1, max_length=100)]


class ReferencePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool = False
    bindings: Annotated[list[ReferenceBinding], Field(max_length=100)] = []


def _not_found():
    return HTTPException(404, "Reference not found")


def reference_scope(request: Request, response: Response, config=Depends(get_config)):
    auth = get_auth_context(request)
    if auth is None or not auth.is_authenticated:
        raise HTTPException(401, "Authentication required")
    if (
        getattr(request.state, "auth_source", None) != "session"
        or getattr(auth.user, "system_role", None) != "client"
        or auth.actor_user_id != str(auth.user.id)
        or not auth.organization_id
        or resolve_organization_id() != auth.organization_id
        or not auth.storage_user_id
        or get_effective_user_id() != auth.storage_user_id
    ):
        raise HTTPException(403, "References are not enabled for this account")
    try:
        policy = ReferencePolicy.model_validate(getattr(config, "client_reference_reads", None) or {})
    except ValidationError:
        raise HTTPException(503, "Reference policy is unavailable") from None
    bindings = [b for b in policy.bindings if b.user_id == auth.actor_user_id and b.organization_id == auth.organization_id]
    if not policy.enabled or not bindings:
        raise HTTPException(403, "References are not enabled for this account")
    # Ambiguous overlapping operator entries fail closed; no union of grants.
    if len({b.project_id for b in bindings}) != len(bindings):
        raise HTTPException(503, "Reference policy is ambiguous")
    response.headers["Cache-Control"] = "no-store"
    return auth.storage_user_id, {b.project_id: b.documents for b in bindings}


async def _project(request, project_id, scope):
    storage_id, bindings = scope
    if project_id not in bindings:
        raise _not_found()
    row = await get_project_repo(request).get(project_id, user_id=storage_id)
    if row is None or row.get("status") != "active":
        raise _not_found()
    return row


def _project_view(row):
    return {key: row[key] for key in ("id", "name", "status")}


async def _document(request, project_id, document_id, scope):
    await _project(request, project_id, scope)
    storage_id, bindings = scope
    digest = bindings[project_id].get(document_id)
    if digest is None:
        raise _not_found()
    row = await get_project_document_repo(request).get(document_id, user_id=storage_id)
    if row is None or row.get("project_id") != project_id or row.get("trashed_at") is not None or row.get("sha256") != digest:
        raise _not_found()
    return row


def _verified_bytes(paths, storage_id, row):
    """Resolve and read original bytes once off-loop, verifying the approved hash."""
    name = row.get("name")
    size = row.get("size_bytes")
    if not isinstance(name, str) or name in {"", ".", ".."} or "/" in name or "\\" in name or type(size) is not int or not 0 <= size <= MAX_DOCUMENT_BYTES:
        return None
    try:
        original, _ = resolve_document_paths(paths, user_id=storage_id, relpath=row["stored_relpath"], name=name)
        with original.open("rb") as source:
            data = source.read(MAX_DOCUMENT_BYTES + 1)
    except (OSError, ValueError):
        return None
    if len(data) != size or hashlib.sha256(data).hexdigest() != row["sha256"]:
        return None
    return data


@router.get("/projects")
async def list_reference_projects(request: Request, scope=Depends(reference_scope)):
    projects = []
    for project_id in scope[1]:
        try:
            projects.append(_project_view(await _project(request, project_id, scope)))
        except HTTPException as error:
            if error.status_code != 404:
                raise
    return {"projects": projects}


@router.get("/projects/{project_id}")
async def get_reference_project(project_id: Identifier, request: Request, scope=Depends(reference_scope)):
    return _project_view(await _project(request, project_id, scope))


@router.get("/projects/{project_id}/documents")
async def list_reference_documents(project_id: Identifier, request: Request, scope=Depends(reference_scope)):
    await _project(request, project_id, scope)
    documents = []
    for document_id in scope[1][project_id]:
        try:
            row = await _document(request, project_id, document_id, scope)
        except HTTPException as error:
            if error.status_code != 404:
                raise
            continue
        data = await run_file_io(_verified_bytes, get_paths(), scope[0], row)
        documents.append({**{key: row[key] for key in ("id", "name", "sha256", "size_bytes")}, "content_missing": data is None})
    return {"documents": documents, "total": len(documents), "limit": 100, "offset": 0}


@router.get("/projects/{project_id}/documents/{document_id}/content")
async def get_reference_content(project_id: Identifier, document_id: Identifier, request: Request, scope=Depends(reference_scope)):
    row = await _document(request, project_id, document_id, scope)
    data = await run_file_io(_verified_bytes, get_paths(), scope[0], row)
    if data is None:
        raise HTTPException(409, "Reference content is unavailable")
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": "attachment; filename*=utf-8''" + quote(row["name"], safe=""), "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )
