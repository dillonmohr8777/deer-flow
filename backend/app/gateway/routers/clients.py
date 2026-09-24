"""CRUD API for the client roster, plus the registry import (Momentum Phase 2 items 2-3).

Route permissions mirror ``projects.py`` (read/write, no owner_check -- the
repository itself is organization scoped). ``POST /import`` is admin-only,
mirroring ``capabilities.py``'s ``install`` route: no ``@require_permission``
decorator, just ``require_admin_user`` inside the body -- an unauthenticated
caller is still rejected by the user lookup it performs.
"""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.gateway.authz import require_permission
from app.gateway.deps import get_client_repo, require_admin_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/clients", tags=["clients"])

ClientStatus = Literal["active", "inactive", "prospect"]
AssignmentRole = Literal["account_manager", "contributor", "client_contact"]
_STATUSES: frozenset[str] = frozenset({"active", "inactive", "prospect"})


class ClientAssignmentResponse(BaseModel):
    user_id: str
    role: str
    created_at: str
    updated_at: str


class ClientResponse(BaseModel):
    id: str
    display_name: str
    aliases: list[str]
    status: str
    email_domains: list[str]
    slack_channel_ids: list[str]
    registry_id: str | None
    notes: str
    created_at: str
    updated_at: str
    assignments: list[ClientAssignmentResponse] = Field(default_factory=list)
    project_count: int = 0


class ClientListResponse(BaseModel):
    clients: list[ClientResponse]


class ClientCreateRequest(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=255)
    aliases: list[str] = Field(default_factory=list)
    status: ClientStatus = "active"
    email_domains: list[str] = Field(default_factory=list)
    slack_channel_ids: list[str] = Field(default_factory=list)
    registry_id: str | None = None
    notes: str = ""


class ClientPatchRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    aliases: list[str] | None = None
    status: ClientStatus | None = None
    email_domains: list[str] | None = None
    slack_channel_ids: list[str] | None = None
    notes: str | None = None


class ClientAssignmentRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    role: AssignmentRole


class RegistryClientEntry(BaseModel):
    """One ``clients[]`` entry from ``client-operations/registry/clients.json``.

    Only the columns ``ClientRow`` actually has are read; ``contacts``,
    ``evidence``, ``folder``, ``accessRefs`` and ``lastEvidenceAt`` have no
    home in this table yet and are dropped (Pydantic ignores unknown fields
    by default -- no ``extra="forbid"`` here on purpose).
    """

    id: str | None = None
    displayName: str | None = None
    aliases: list[str] = Field(default_factory=list)
    status: str = "active"
    emailDomains: list[str] = Field(default_factory=list)
    slackChannels: list[str] = Field(default_factory=list)


class RegistryImportRequest(BaseModel):
    clients: list[RegistryClientEntry]


class RegistryImportResponse(BaseModel):
    created: int
    updated: int
    skipped: int
    skipped_ids: list[str] = Field(default_factory=list)


def _not_found() -> HTTPException:
    # Fail closed: foreign clients are indistinguishable from missing ones.
    return HTTPException(status_code=404, detail="Client not found")


def _to_response(row: dict, *, assignments: list[dict] | None = None, project_count: int = 0) -> ClientResponse:
    return ClientResponse(
        id=row["id"],
        display_name=row["display_name"],
        aliases=row.get("aliases") or [],
        status=row["status"],
        email_domains=row.get("email_domains") or [],
        slack_channel_ids=row.get("slack_channel_ids") or [],
        registry_id=row.get("registry_id"),
        notes=row.get("notes", ""),
        created_at=row.get("created_at", ""),
        updated_at=row.get("updated_at", ""),
        assignments=[ClientAssignmentResponse(**a) for a in (assignments or [])],
        project_count=project_count,
    )


async def _to_list_response(repo, rows: list[dict]) -> ClientListResponse:
    ids = [row["id"] for row in rows]
    counts, assignments = await repo.project_counts(ids), await repo.assignments_by_client(ids)
    return ClientListResponse(clients=[_to_response(row, assignments=assignments.get(row["id"], []), project_count=counts.get(row["id"], 0)) for row in rows])


@router.post("", response_model=ClientResponse, status_code=201)
@require_permission("clients", "write")
async def create_client(body: ClientCreateRequest, request: Request) -> ClientResponse:
    repo = get_client_repo(request)
    row = await repo.create(
        display_name=body.display_name,
        aliases=body.aliases,
        status=body.status,
        email_domains=body.email_domains,
        slack_channel_ids=body.slack_channel_ids,
        registry_id=body.registry_id,
        notes=body.notes,
    )
    return _to_response(row)


@router.get("", response_model=ClientListResponse)
@require_permission("clients", "read")
async def list_clients(request: Request, status: ClientStatus | None = None) -> ClientListResponse:
    repo = get_client_repo(request)
    return await _to_list_response(repo, await repo.list(status=status))


@router.get("/mine", response_model=ClientListResponse)
@require_permission("clients", "read")
async def list_my_clients(request: Request) -> ClientListResponse:
    """Clients the caller is assigned to. Declared before ``/{client_id}`` so
    ``mine`` is never parsed as an id, mirroring ``projects.py``'s ``/config``."""
    repo = get_client_repo(request)
    return await _to_list_response(repo, await repo.list_mine())


@router.post("/import", response_model=RegistryImportResponse)
async def import_client_registry(body: RegistryImportRequest, request: Request) -> RegistryImportResponse:
    """Admin-only upsert of the canonical client registry by ``registry_id``.

    Never deletes. Owners are not structured in the registry yet, so this
    never touches ``client_assignments``.
    """
    await require_admin_user(request, detail="Admin privileges required to import the client registry.")
    repo = get_client_repo(request)
    created = updated = 0
    skipped_ids: list[str] = []
    for entry in body.clients:
        if not entry.id or not entry.displayName:
            skipped_ids.append(entry.id or "<missing id>")
            continue
        status = entry.status if entry.status in _STATUSES else "active"
        outcome, _row = await repo.upsert_by_registry_id(
            registry_id=entry.id,
            display_name=entry.displayName,
            aliases=entry.aliases,
            status=status,
            email_domains=entry.emailDomains,
            slack_channel_ids=entry.slackChannels,
        )
        if outcome == "created":
            created += 1
        elif outcome == "updated":
            updated += 1
        else:
            skipped_ids.append(entry.id)
    return RegistryImportResponse(created=created, updated=updated, skipped=len(skipped_ids), skipped_ids=skipped_ids)


@router.get("/{client_id}", response_model=ClientResponse)
@require_permission("clients", "read")
async def get_client(client_id: str, request: Request) -> ClientResponse:
    repo = get_client_repo(request)
    row = await repo.get(client_id)
    if row is None:
        raise _not_found()
    assignments = await repo.list_assignments(client_id) or []
    counts = await repo.project_counts([client_id])
    return _to_response(row, assignments=assignments, project_count=counts.get(client_id, 0))


@router.patch("/{client_id}", response_model=ClientResponse)
@require_permission("clients", "write")
async def patch_client(client_id: str, body: ClientPatchRequest, request: Request) -> ClientResponse:
    repo = get_client_repo(request)
    row = await repo.patch(
        client_id,
        display_name=body.display_name,
        aliases=body.aliases,
        status=body.status,
        email_domains=body.email_domains,
        slack_channel_ids=body.slack_channel_ids,
        notes=body.notes,
    )
    if row is None:
        raise _not_found()
    return _to_response(row)


@router.post("/{client_id}/archive", response_model=ClientResponse)
@require_permission("clients", "write")
async def archive_client(client_id: str, request: Request) -> ClientResponse:
    repo = get_client_repo(request)
    row = await repo.set_status(client_id, "inactive")
    if row is None:
        raise _not_found()
    return _to_response(row)


@router.post("/{client_id}/assignments", response_model=ClientAssignmentResponse, status_code=201)
@require_permission("clients", "write")
async def add_client_assignment(client_id: str, body: ClientAssignmentRequest, request: Request) -> ClientAssignmentResponse:
    repo = get_client_repo(request)
    row = await repo.add_assignment(client_id, body.user_id, body.role)
    if row is None:
        raise _not_found()
    return ClientAssignmentResponse(**row)


@router.delete("/{client_id}/assignments/{user_id}", status_code=204)
@require_permission("clients", "write")
async def remove_client_assignment(client_id: str, user_id: str, request: Request) -> None:
    repo = get_client_repo(request)
    if await repo.get(client_id) is None:
        raise _not_found()
    await repo.remove_assignment(client_id, user_id)
