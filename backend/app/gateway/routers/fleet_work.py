"""Host-facing lease API for fleet-executed subagent batch items.

Remote hosts (Mac mini, Windows PC, Codex Cloud, AWS later) run
``fleet/runner/runner.py`` and claim work here. The items are the same durable
``subagent_batch_items`` rows the native ``SubagentBatchService`` leases, so the
stable ``item_key``, ``lease_owner`` fencing, attempt counting, expiry
recovery and cancellation are reused unchanged. The only partition is
``execution_spec["executor"] == "fleet"``, which the native service never
claims. Callers are internal delegations (``X-DeerFlow-Internal-Token`` plus
``X-DeerFlow-Delegation-Id``) whose scopes include ``fleet:work``.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field, model_validator

from app.gateway.authz import require_permission
from app.gateway.deps import get_client_repo, get_current_user, get_current_user_from_request, get_subagent_batch_repo
from app.gateway.internal_auth import get_trusted_internal_owner_user_id
from app.gateway.routers.clients import _is_active_org_admin, _require_client_visible
from deerflow.config.roster_config import RosterConfig, client_allowed, scope_for
from deerflow.config.subagent_batches_config import SubagentBatchesConfig
from deerflow.runtime.user_context import resolve_organization_id

router = APIRouter(prefix="/api/fleet/work", tags=["fleet-work"])

FLEET_EXECUTOR = "fleet"
Lane = Literal["haiku", "spark", "morph", "sonnet", "luna", "ultrafast", "desktop"]
DataClass = Literal["public", "synthetic", "private"]
Project = Literal["philadelphia", "backend", "prospect-radar", "outreach"]
PROJECTS = ("philadelphia", "backend", "prospect-radar", "outreach")
# Contributor and Ultrafast routes are not admitted for client/private text.
PUBLIC_ONLY_LANES = frozenset({"spark", "ultrafast"})
# "desktop" runs on a Mac host through the MomoBot desktop bridge. Private data is
# allowed, it never retries (a prompt can have side effects), and it stays
# unclaimable until an org owner/admin approves it (approval_state).
DESKTOP_LANE = "desktop"
_MAX_ERROR_CHARS = 4_000
_LEASE_OWNER_FIELD = Field(min_length=1, max_length=128)


class FleetItemInput(BaseModel):
    key: str = Field(min_length=1, max_length=128)
    prompt: str = Field(min_length=1)


class SlackOrigin(BaseModel):
    """Where a Slack-submitted desktop job posts its result (desktop lane only)."""

    channel: str = Field(min_length=1, max_length=32, pattern=r"^[A-Z0-9]+$")
    team: str | None = Field(default=None, max_length=32, pattern=r"^[A-Z0-9]+$")
    connection: str | None = Field(default=None, max_length=64)


class WorkspaceSpec(BaseModel):
    environment_id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,62}$")
    command: list[str] = Field(min_length=1, max_length=32)
    timeout_seconds: int = Field(default=300, ge=1, le=3600)
    client_path: str | None = Field(default=None, min_length=1, max_length=4096)

    @model_validator(mode="after")
    def validate_workspace(self) -> WorkspaceSpec:
        if any(not part or len(part) > 8192 for part in self.command):
            raise ValueError("Workspace command contains an invalid argument")
        if self.client_path is not None and (not self.client_path.startswith("/") or ".." in self.client_path.split("/")):
            raise ValueError("Workspace client path must be absolute and traversal-free")
        return self


class FleetBatchSubmit(BaseModel):
    thread_id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=256)
    lane: Lane
    data_class: DataClass
    items: list[FleetItemInput] = Field(min_length=1)
    submission_key: str = Field(min_length=1, max_length=256)
    max_running_items: int | None = Field(default=None, ge=1)
    max_attempts: int | None = Field(default=None, ge=1)
    max_tokens: int | None = Field(default=None, ge=16, le=32_768)
    effort: Literal["low", "medium", "high"] = "high"
    project: Project | None = None
    source_ref: str | None = Field(default=None, min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
    workspace: WorkspaceSpec | None = None
    client_id: str | None = Field(default=None, min_length=1, max_length=96, pattern=r"^[a-z0-9][a-z0-9-]{0,95}$")
    requester: str | None = Field(default=None, min_length=1, max_length=64, pattern=r"^[A-Z0-9]+$")  # Slack user id, desktop lane only
    slack_origin: SlackOrigin | None = None  # desktop lane only

    @model_validator(mode="after")
    def validate_project_binding(self) -> FleetBatchSubmit:
        if self.workspace is not None:
            if self.max_running_items is not None and self.max_running_items > 3:
                raise ValueError("Linux workspaces preserve the three-worker ceiling")
            if self.workspace.client_path is not None and self.client_id is None:
                raise ValueError("A workspace client mount requires an admitted client ID")
        if self.lane == DESKTOP_LANE:
            if self.client_id is None or self.requester is None or self.project is not None or self.source_ref is not None:
                raise ValueError("Desktop jobs require client_id and requester, and take no project")
            return self
        if self.requester is not None or self.slack_origin is not None:
            raise ValueError("requester and slack_origin are only valid on the desktop lane")
        if (self.project is None) != (self.source_ref is None):
            raise ValueError("Project jobs require both project and a safe canonical source reference")
        if self.source_ref is not None and (".." in self.source_ref or "//" in self.source_ref):
            raise ValueError("Project source reference contains an unsafe path segment")
        if self.client_id is not None:
            if self.project is None or self.source_ref != f"client-operations-canonical:client/{self.client_id}":
                raise ValueError("Client jobs require an exact canonical source reference")
            if self.lane != "haiku" or self.data_class != "private":
                raise ValueError("Client jobs require private Haiku")
        elif self.source_ref and self.source_ref.startswith("client-operations-canonical:client/"):
            raise ValueError("Canonical client source requires an admitted client ID")
        return self


class ClaimRequest(BaseModel):
    lease_owner: str = _LEASE_OWNER_FIELD
    lanes: list[Lane] = Field(min_length=1)
    limit: int = Field(default=1, ge=1, le=64)
    batch_id: str | None = Field(default=None, min_length=1, max_length=64)  # runner --batch-id selector


class LeaseRequest(BaseModel):
    lease_owner: str = _LEASE_OWNER_FIELD


class ReleaseRequest(LeaseRequest):
    error: str | None = None


class FinalizeRequest(LeaseRequest):
    succeeded: bool
    result: str | None = None
    error: str | None = None
    model_name: str | None = Field(default=None, max_length=128)
    stop_reason: str | None = Field(default=None, max_length=64)
    token_usage: dict[str, Any] | None = None


def _roster(request: Request) -> RosterConfig:
    config = getattr(request.app.state, "roster_config", None)
    return config if isinstance(config, RosterConfig) else RosterConfig()  # fail closed: empty roster denies everyone


def _config(request: Request) -> SubagentBatchesConfig:
    config = getattr(request.app.state, "subagent_batches_config", None)
    return config if isinstance(config, SubagentBatchesConfig) else SubagentBatchesConfig()


async def _owner(request: Request) -> str:
    user_id = await get_current_user(request)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user_id


def _trusted_fleet_owner(request: Request) -> tuple[str, str]:
    owner = get_trusted_internal_owner_user_id(request)
    organization_id = getattr(request.state, "organization_id", None)
    if owner is None or not isinstance(organization_id, str) or not organization_id:
        raise HTTPException(status_code=403, detail="Internal fleet delegation required")
    return owner, organization_id


async def _require_owned_lease(request: Request, item_id: str, lease_owner: str) -> None:
    owner, organization_id = _trusted_fleet_owner(request)
    if not await get_subagent_batch_repo(request).owns_fleet_item_lease(item_id, lease_owner=lease_owner, owner_id=owner, organization_id=organization_id):
        raise HTTPException(status_code=404, detail="Fleet lease not found")


async def _require_canonical_client_access(request: Request, client_id: str, *, owner_id: str) -> None:
    """Prove the actor may use an active imported canonical client.

    A request's storage principal owns the durable batch. Its authenticated
    actor must currently be an org owner/admin or assigned to the imported
    client. The host broker separately re-reads the canonical source itself.
    """
    state = request.state
    organization_id = resolve_organization_id()
    actor_id = getattr(state, "actor_user_id", None)
    if not organization_id or organization_id != getattr(state, "organization_id", None) or owner_id != getattr(state, "storage_user_id", None) or not isinstance(actor_id, str) or not actor_id:
        raise HTTPException(status_code=404, detail="Client job not found")
    client_repo = get_client_repo(request)
    row = next((row for row in await client_repo.list(status="active") if row.get("registry_id") == client_id), None)
    if row is None:
        raise HTTPException(status_code=404, detail="Client job not found")
    await _require_client_visible(client_repo, row["id"], actor_id)


def _bounded_error(error: str | None) -> str | None:
    return error[:_MAX_ERROR_CHARS] if error else None


def claimed_view(item: dict[str, Any], *, lease_expires_at: str) -> dict[str, Any]:
    """Return what a host needs to execute: identity, lease, prompt and lane policy."""
    spec = (item.get("batch") or {}).get("execution_spec") or {}
    return {
        "id": item["id"],
        "batch_id": item["batch_id"],
        "item_key": item["item_key"],
        "attempt": item["attempt"],
        "max_attempts": (item.get("batch") or {}).get("max_attempts"),
        "lease_expires_at": lease_expires_at,
        "prompt": item["prompt"],
        "acceptance_criteria": item.get("acceptance_criteria"),
        "lane": spec.get("lane"),
        "data_class": spec.get("data_class"),
        "max_tokens": spec.get("max_tokens"),
        "effort": spec.get("effort"),
        "project": spec.get("project"),
        "workspace": spec.get("workspace"),
        "client_id": spec.get("client_id"),
        "requester": spec.get("requester"),
        "approval_state": spec.get("approval_state", "none"),
        "source_ref": spec.get("source_ref"),
        "output_policy": spec.get("output_policy", "draft-only"),
    }


@router.post("/batches", status_code=201)
@require_permission("fleet", "work")
async def submit_fleet_batch(request: Request, body: FleetBatchSubmit) -> dict[str, Any]:
    """Queue one fleet batch; idempotent on ``submission_key`` like native batches."""
    if body.lane in PUBLIC_ONLY_LANES and body.data_class == "private":
        raise HTTPException(status_code=422, detail=f"Lane {body.lane} accepts public or synthetic data only")
    if body.lane == "ultrafast":
        if body.max_attempts not in (None, 1) or (body.max_tokens is not None and body.max_tokens > 4096):
            raise HTTPException(status_code=422, detail="Ultrafast requires one attempt and at most 4096 output tokens")
        if any(len(item.prompt.encode("utf-8")) > 16_000 for item in body.items):
            raise HTTPException(status_code=422, detail="Ultrafast prompt exceeds 16000 UTF-8 bytes")
    if body.lane == DESKTOP_LANE:
        if body.max_attempts not in (None, 1):
            raise HTTPException(status_code=422, detail="Desktop jobs run once (max_attempts 1)")
        if not client_allowed(scope_for(_roster(request), body.requester), body.client_id):
            raise HTTPException(status_code=403, detail="Requester is not rostered for this client")
    config = _config(request)
    if len(body.items) > config.max_items_per_batch:
        raise HTTPException(status_code=422, detail=f"Batch item count must be between 1 and {config.max_items_per_batch}")
    keys = [item.key for item in body.items]
    if len(set(keys)) != len(keys):
        raise HTTPException(status_code=422, detail="Item keys must be unique within a batch")
    max_running = config.default_max_running_items if body.max_running_items is None else body.max_running_items
    if max_running > config.max_running_items_per_batch:
        raise HTTPException(status_code=422, detail=f"max_running_items must not exceed {config.max_running_items_per_batch}")
    max_attempts = 1 if body.lane in ("ultrafast", DESKTOP_LANE) else config.max_attempts if body.max_attempts is None else body.max_attempts
    if max_attempts > config.max_attempts:
        raise HTTPException(status_code=422, detail=f"max_attempts must not exceed {config.max_attempts}")
    max_live = min(max(config.default_max_live_items, max_running), config.max_live_items_per_batch)
    owner = await _owner(request)
    repo = get_subagent_batch_repo(request)
    if body.project is not None and not await repo.owns_thread_for_fleet_project(thread_id=body.thread_id, user_id=owner):
        raise HTTPException(status_code=404, detail="Project thread not found")
    if body.client_id is not None and body.lane != DESKTOP_LANE:
        await _require_canonical_client_access(request, body.client_id, owner_id=owner)
    try:
        return await repo.create_batch(
            batch_id=f"fleet-batch-{uuid.uuid4().hex}",
            user_id=owner,
            thread_id=body.thread_id,
            run_id=None,
            tool_call_id=None,
            submission_key=(
                hashlib.sha256(f"desktop:{body.requester}:{body.client_id}:{body.submission_key}".encode()).hexdigest()
                if body.lane == DESKTOP_LANE
                else hashlib.sha256((f"project:{body.project}:client:{body.client_id}:{body.submission_key}" if body.client_id else f"project:{body.project}:{body.submission_key}").encode()).hexdigest()
                if body.project
                else body.submission_key
            ),
            title=body.title,
            subagent_type=f"fleet-{body.lane}@{body.project}" if body.project else f"fleet-{body.lane}",
            items=[{"key": item.key, "prompt": item.prompt} for item in body.items],
            max_live_items=max_live,
            max_running_items=max_running,
            max_attempts=max_attempts,
            execution_spec={
                "executor": FLEET_EXECUTOR,
                "lane": body.lane,
                "data_class": body.data_class,
                "effort": body.effort,
                "max_tokens": 4096 if body.lane == "ultrafast" and body.max_tokens is None else body.max_tokens,
                **({"workspace": body.workspace.model_dump(exclude_none=True)} if body.workspace else {}),
                **({"project": body.project, "source_ref": body.source_ref, "output_policy": "draft-only"} if body.project else {}),
                **({"client_id": body.client_id} if body.client_id else {}),
                **({"requester": body.requester, "approval_state": "pending", "output_policy": "draft-only"} if body.lane == DESKTOP_LANE else {}),
                **({"slack_origin": body.slack_origin.model_dump(exclude_none=True)} if body.slack_origin else {}),
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/batches/{batch_id}/approve")
@require_permission("approvals", "write")
async def approve_desktop_batch(batch_id: str, request: Request) -> dict[str, Any]:
    """Release a pending desktop batch to the host. Org owner/admin only; repeat approvals are no-ops."""
    reviewer = str((await get_current_user_from_request(request)).id)
    if not await _is_active_org_admin(reviewer):
        raise HTTPException(status_code=403, detail="Only an organization owner or admin can approve desktop jobs.")
    batch = await get_subagent_batch_repo(request).approve_fleet_batch(batch_id, approver_id=reviewer, now=datetime.now(UTC))
    if batch is None:
        raise HTTPException(status_code=404, detail="Desktop job not found")
    return batch


@router.post("/batches/{batch_id}/reject")
@require_permission("approvals", "write")
async def reject_desktop_batch(batch_id: str, request: Request) -> dict[str, Any]:
    """Cancel a pending desktop batch before it reaches the host. Org owner/admin only."""
    reviewer = str((await get_current_user_from_request(request)).id)
    if not await _is_active_org_admin(reviewer):
        raise HTTPException(status_code=403, detail="Only an organization owner or admin can reject desktop jobs.")
    batch = await get_subagent_batch_repo(request).reject_fleet_batch(batch_id, approver_id=reviewer, now=datetime.now(UTC))
    if batch is None:
        raise HTTPException(status_code=404, detail="Desktop job not found")
    if batch["approval_state"] != "rejected":
        raise HTTPException(status_code=409, detail="Desktop job was already approved")
    return batch


@router.post("/claim")
@require_permission("fleet", "work")
async def claim_work(request: Request, body: ClaimRequest) -> dict[str, Any]:
    """Atomically lease up to ``limit`` queued fleet items in the requested lanes."""
    trusted_owner, organization_id = _trusted_fleet_owner(request)
    config = _config(request)
    now = datetime.now(UTC)
    items = await get_subagent_batch_repo(request).claim_items(
        now=now,
        lease_owner=body.lease_owner,
        lease_seconds=config.lease_seconds,
        limit=body.limit,
        executor=FLEET_EXECUTOR,
        lanes=set(body.lanes),
        owner_id=trusted_owner,
        organization_id=organization_id,
        batch_id=body.batch_id,
    )
    expires_at = (now + timedelta(seconds=config.lease_seconds)).isoformat()
    return {
        "lease_seconds": config.lease_seconds,
        "items": [claimed_view(item, lease_expires_at=expires_at) for item in items],
    }


@router.post("/{item_id}/renew")
@require_permission("fleet", "work")
async def renew_work(item_id: str, request: Request, body: LeaseRequest) -> dict[str, Any]:
    await _require_owned_lease(request, item_id, body.lease_owner)
    config = _config(request)
    lease = await get_subagent_batch_repo(request).renew_item_lease(
        item_id,
        lease_owner=body.lease_owner,
        lease_seconds=config.lease_seconds,
        now=datetime.now(UTC),
    )
    return {"valid": lease["valid"], "cancel_requested": lease["cancel_requested"], "lease_seconds": config.lease_seconds}


@router.post("/{item_id}/running")
@require_permission("fleet", "work")
async def mark_work_running(item_id: str, request: Request, body: LeaseRequest) -> dict[str, Any]:
    await _require_owned_lease(request, item_id, body.lease_owner)
    ok = await get_subagent_batch_repo(request).mark_item_running(item_id, lease_owner=body.lease_owner, now=datetime.now(UTC))
    if not ok:
        raise HTTPException(status_code=409, detail="Lease not held, already running, or cancelled")
    return {"ok": True}


@router.get("/{item_id}/client-lease")
@require_permission("fleet", "work")
async def verify_client_lease(
    item_id: str,
    request: Request,
    lease_owner: str = Query(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9:_-]{0,127}$"),
) -> dict[str, Any]:
    """Return only fresh, server-derived lease proof to a delegated host."""
    trusted_owner, _organization_id = _trusted_fleet_owner(request)
    lease = await get_subagent_batch_repo(request).verify_private_fleet_lease(item_id, lease_owner=lease_owner, owner_id=trusted_owner, now=datetime.now(UTC))
    if lease is None:
        raise HTTPException(status_code=404, detail="Client lease not found")
    await _require_canonical_client_access(request, lease["client_id"], owner_id=trusted_owner)
    return lease


@router.post("/{item_id}/finalize")
@require_permission("fleet", "work")
async def finalize_work(item_id: str, request: Request, body: FinalizeRequest) -> dict[str, Any]:
    """Store a bounded result (or a retryable error) under the same lease fence as native items."""
    await _require_owned_lease(request, item_id, body.lease_owner)
    config = _config(request)
    raw = body.result or ""
    truncated = body.succeeded and len(raw) > config.max_result_chars
    ok = await get_subagent_batch_repo(request).finalize_item(
        item_id,
        lease_owner=body.lease_owner,
        succeeded=body.succeeded,
        result=raw[: config.max_result_chars] if body.succeeded and raw else None,
        result_preview=raw[: config.result_preview_max_chars] if body.succeeded and raw else None,
        result_truncated=truncated,
        error=_bounded_error(body.error),
        stop_reason=body.stop_reason,
        token_usage=body.token_usage,
        model_name=body.model_name,
        completed_at=datetime.now(UTC),
    )
    if not ok:
        raise HTTPException(status_code=409, detail="Lease not held; result discarded")
    return {"ok": True, "result_truncated": truncated}


@router.post("/{item_id}/release")
@require_permission("fleet", "work")
async def release_work(item_id: str, request: Request, body: ReleaseRequest) -> dict[str, Any]:
    """Hand an unstarted or interrupted item back without consuming its attempt."""
    await _require_owned_lease(request, item_id, body.lease_owner)
    ok = await get_subagent_batch_repo(request).requeue_item_after_admission_failure(
        item_id,
        lease_owner=body.lease_owner,
        error=_bounded_error(body.error),
        now=datetime.now(UTC),
    )
    if not ok:
        raise HTTPException(status_code=409, detail="Lease not held; nothing released")
    return {"ok": True}


@router.get("/projects")
@require_permission("fleet", "work")
async def list_project_bindings(request: Request) -> dict[str, Any]:
    """Named work lanes, not a second registry or independently activated schedule."""
    await _owner(request)
    return {"projects": [{"id": project, "output_policy": "draft-only", "schedule_active": False} for project in PROJECTS], "queue": "subagent_batches", "canonical_queue_writer": "Marketing Chief"}


async def _owned_project_batch(request: Request, project: Project, batch_id: str) -> tuple[Any, str, dict[str, Any]]:
    owner = await _owner(request)
    repo = get_subagent_batch_repo(request)
    batch = await repo.get_batch(batch_id, user_id=owner)
    if batch is None or not batch.get("subagent_type", "").endswith(f"@{project}"):
        raise HTTPException(status_code=404, detail="Project job not found")
    return repo, owner, batch


@router.get("/projects/{project}/batches/{batch_id}")
@require_permission("fleet", "work")
async def get_project_job(project: Project, batch_id: str, request: Request) -> dict[str, Any]:
    _repo, _owner_id, batch = await _owned_project_batch(request, project, batch_id)
    return {"project": project, "output_policy": "draft-only", "batch": batch}


@router.post("/projects/{project}/batches/{batch_id}/cancel")
@require_permission("fleet", "work")
async def cancel_project_job(project: Project, batch_id: str, request: Request) -> dict[str, Any]:
    repo, owner, _batch = await _owned_project_batch(request, project, batch_id)
    # The durable cancel flag invalidates host leases; the existing renew loop
    # stops running subprocesses. No native worker must be activated to cancel.
    batch = await repo.cancel_batch(batch_id, user_id=owner)
    if batch is None:
        raise HTTPException(status_code=404, detail="Project job not found")
    return {"project": project, "output_policy": "draft-only", "batch": batch}
