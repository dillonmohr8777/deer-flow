"""CRUD API for the client roster, plus the registry import (Momentum Phase 2 items 2-3).

Route permissions mirror ``projects.py`` (read/write, no owner_check -- the
repository itself is organization scoped). ``POST /import`` is admin-only,
mirroring ``capabilities.py``'s ``install`` route: no ``@require_permission``
decorator, just ``require_admin_user`` inside the body -- an unauthenticated
caller is still rejected by the user lookup it performs.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.gateway.authz import require_permission
from app.gateway.deps import (
    get_client_repo,
    get_current_user_from_request,
    get_fleet_binding_repo,
    get_scheduled_task_repo,
    record_audit_event,
    require_admin_user,
)
from deerflow.config.agents_config import load_agent_config
from deerflow.fleet import FleetTemplate, FleetTemplateError, load_fleet_template
from deerflow.persistence.agents import AgentExistsError, get_agent_store
from deerflow.persistence.fleet import FleetBindingExistsError
from deerflow.persistence.organizations.model import OrganizationMemberRow
from deerflow.runtime.user_context import get_effective_user_id, resolve_organization_id
from deerflow.scheduler.schedules import next_run_at as compute_next_run_at

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/clients", tags=["clients"])

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_ORG_ADMIN_ROLES = ("owner", "admin")

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


# ---------------------------------------------------------------------------
# Fleet template stamping (fleet foundation item 4): turn a template + this
# client into a real custom agent and a paused, non-interactive scheduled
# task. See ``deerflow.fleet`` for the template catalog and
# ``fleet.py``'s ``GET /api/fleet/templates`` for listing it.
# ---------------------------------------------------------------------------


class StampClientAgentRequest(BaseModel):
    template_id: str = Field(..., min_length=1)


class FleetAgentBindingResponse(BaseModel):
    client_id: str
    template_id: str
    template_version: str
    agent_name: str
    display_name: str | None = None
    description: str | None = None
    scheduled_task_id: str | None = None
    created_at: str
    updated_at: str


class FleetAgentBindingListResponse(BaseModel):
    agents: list[FleetAgentBindingResponse]


def _slugify(value: str) -> str:
    slug = _SLUG_RE.sub("-", value.strip().lower()).strip("-")
    return slug or "client"


async def _is_active_org_admin(user_id: str) -> bool:
    """Whether *user_id* is an active owner/admin of the caller's active organization."""
    organization_id = resolve_organization_id()
    if organization_id is None:
        return False
    # Lazy import: resolved at call time, not at module import time, so a
    # test's ``monkeypatch.setattr("deerflow.persistence.engine.get_session_factory", ...)``
    # (org_isolation_fixtures.org_world) takes effect; a module-level
    # ``from ... import get_session_factory`` would bind the pre-patch
    # function forever. Mirrors ``routers/invitations.py``'s ``_session_factory()``.
    from deerflow.persistence.engine import get_session_factory

    session_factory = get_session_factory()
    if session_factory is None:
        return False
    stmt = select(OrganizationMemberRow.user_id).where(
        OrganizationMemberRow.organization_id == organization_id,
        OrganizationMemberRow.user_id == user_id,
        OrganizationMemberRow.status == "active",
        OrganizationMemberRow.role.in_(_ORG_ADMIN_ROLES),
    )
    async with session_factory() as session:
        return (await session.execute(stmt)).scalars().first() is not None


async def _require_stamp_authorized(request: Request, client_id: str, client_repo: Any) -> Any:
    """Only an organization admin or someone assigned to *client_id* may stamp an agent."""
    user = await get_current_user_from_request(request)
    if await _is_active_org_admin(str(user.id)):
        return user
    assignments = await client_repo.list_assignments(client_id) or []
    if any(a["user_id"] == str(user.id) for a in assignments):
        return user
    raise HTTPException(status_code=403, detail="Only an organization admin or someone assigned to this client can stamp an agent.")


async def _binding_response(binding: dict) -> FleetAgentBindingResponse:
    try:
        agent_cfg = await asyncio.to_thread(load_agent_config, binding["agent_name"], user_id=binding["agent_owner_user_id"])
    except FileNotFoundError:
        agent_cfg = None
    return FleetAgentBindingResponse(
        client_id=binding["client_id"],
        template_id=binding["template_id"],
        template_version=binding["template_version"],
        agent_name=binding["agent_name"],
        display_name=(agent_cfg.display_name if agent_cfg else None),
        description=(agent_cfg.description if agent_cfg else None),
        scheduled_task_id=binding.get("scheduled_task_id"),
        created_at=binding["created_at"],
        updated_at=binding["updated_at"],
    )


async def _create_paused_schedule(request: Request, template: FleetTemplate, client_display_name: str, agent_name: str, owner_user_id: str, actor_user_id: str) -> str:
    """Create a scheduled task from the template's suggested schedule, then pause it.

    The person turns it on; stamping never starts anything running.
    """
    schedule_repo = get_scheduled_task_repo(request)
    schedule_spec = {"cron": template.schedule.cron}
    next_at = compute_next_run_at("cron", schedule_spec, template.schedule.timezone, now=datetime.now(UTC))
    task = await schedule_repo.create(
        task_id=f"task-{uuid.uuid4().hex}",
        user_id=owner_user_id,
        thread_id=None,
        context_mode="fresh_thread_per_run",
        assistant_id=agent_name,
        title=f"{template.name} for {client_display_name}",
        prompt=f"Run today's {template.name.lower()} for {client_display_name}.",
        schedule_type="cron",
        schedule_spec=schedule_spec,
        timezone=template.schedule.timezone,
        next_run_at=next_at,
        delegation_owner_user_id=actor_user_id,
    )
    await schedule_repo.pause_with_queue_cancellation(task["id"], user_id=owner_user_id, error="Created paused by fleet template stamping.", now=datetime.now(UTC))
    return task["id"]


@router.get("/{client_id}/agents", response_model=FleetAgentBindingListResponse)
@require_permission("clients", "read")
async def list_client_agents(client_id: str, request: Request) -> FleetAgentBindingListResponse:
    client_repo = get_client_repo(request)
    if await client_repo.get(client_id) is None:
        raise _not_found()
    binding_repo = get_fleet_binding_repo(request)
    bindings = await binding_repo.list_by_client(client_id)
    return FleetAgentBindingListResponse(agents=[await _binding_response(b) for b in bindings])


@router.post("/{client_id}/agents", response_model=FleetAgentBindingResponse, status_code=201)
@require_permission("clients", "write")
async def stamp_client_agent(client_id: str, body: StampClientAgentRequest, request: Request, response: Response) -> FleetAgentBindingResponse:
    """Stamp a fleet template into a real agent for this client.

    Idempotent: stamping the same template twice for one client returns the
    existing agent (HTTP 200) instead of creating a second one (HTTP 201, the
    route's default). Only an organization admin or someone assigned to this
    client (``client_assignments``) may call this.
    """
    client_repo = get_client_repo(request)
    client = await client_repo.get(client_id)
    if client is None:
        raise _not_found()

    user = await _require_stamp_authorized(request, client_id, client_repo)

    template_id = body.template_id.strip()
    try:
        template = await asyncio.to_thread(load_fleet_template, template_id)
    except FleetTemplateError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if template is None:
        raise HTTPException(status_code=404, detail=f"Unknown fleet template '{template_id}'")

    binding_repo = get_fleet_binding_repo(request)
    existing = await binding_repo.get_by_client_and_template(client_id, template.id)
    if existing is not None:
        response.status_code = 200
        return await _binding_response(existing)

    owner_user_id = get_effective_user_id()
    agent_name = f"{_slugify(client['display_name'])}-{template.id}"
    config_data: dict[str, Any] = {
        "name": agent_name,
        "description": template.description,
        "model": template.model,
        "skills": template.skills,
        "tool_groups": template.tool_groups or None,
        "mcp_plugins": template.mcp_plugins or None,
        "client_id": client_id,
        "template_id": template.id,
        "template_version": template.version,
    }
    soul_text = template.render_soul(client_name=client["display_name"])

    store = get_agent_store()
    try:
        await asyncio.to_thread(store.create, agent_name, config_data, soul_text, user_id=owner_user_id)
    except AgentExistsError as exc:
        # Deterministic name collision with no binding row: either a manual
        # agent already used this exact name, or a concurrent stamp request
        # for this same (client, template) raced us here.
        raced = await binding_repo.get_by_client_and_template(client_id, template.id)
        if raced is not None:
            response.status_code = 200
            return await _binding_response(raced)
        raise HTTPException(status_code=409, detail=f"Agent '{agent_name}' already exists") from exc

    try:
        scheduled_task_id = await _create_paused_schedule(request, template, client["display_name"], agent_name, owner_user_id, str(user.id))
    except Exception as exc:
        await asyncio.to_thread(store.delete, agent_name, user_id=owner_user_id)
        logger.exception("Fleet stamping: rolled back agent '%s' after its scheduled task failed to create", agent_name)
        raise HTTPException(status_code=500, detail="Failed to create the agent's scheduled task; the agent was not created.") from exc

    try:
        created = await binding_repo.create(
            client_id=client_id,
            template_id=template.id,
            template_version=template.version,
            agent_name=agent_name,
            agent_owner_user_id=owner_user_id,
            scheduled_task_id=scheduled_task_id,
        )
    except FleetBindingExistsError:
        raced = await binding_repo.get_by_client_and_template(client_id, template.id)
        if raced is None:
            raise
        created = raced

    await record_audit_event(
        request,
        action="fleet.agent.stamped",
        outcome="success",
        actor_user_id=str(user.id),
        target_type="agent",
        target_id=agent_name,
        details={"client_id": client_id, "template_id": template.id, "template_version": template.version},
    )
    return await _binding_response(created)
