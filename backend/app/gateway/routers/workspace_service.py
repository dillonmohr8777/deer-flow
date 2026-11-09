"""Workspace service tier, seller attribution and the seller onboarding call.

Everything here is behind ``service_tiers.enabled`` (off by default): while it
is off every route answers 404 and nothing is read or written.

* ``GET /api/workspaces/{id}/service``: any non-client member reads the tier.
* ``PUT /api/workspaces/{id}/service``: an owner or admin sets the tier, the
  seller and the software-tier "Book a call" link, under compare-and-set.
* ``POST /api/onboarding/{id}/preview``: turns pasted contract scope into a
  work plan. No writes.
* ``POST /api/onboarding/{id}/apply``: names the workspace, stores the plan and
  creates its recurring tasks PAUSED, so nothing runs until a person resumes
  each one in Scheduled tasks. Every task only drafts for review; none
  publishes, posts or sends.

Onboarding lives outside ``/api/workspaces`` on purpose: AuthMiddleware pins
every ``/api/workspaces`` request to the caller's private workspace, while the
onboarding tasks must be created inside the workspace being set up. Under
``/api/onboarding`` the workspace-selection cookie applies, so the middleware
has already proven the caller's membership of the active workspace and the
scheduled tasks land in it. ``apply`` refuses unless the active workspace is
the one in the path.

Tier names only: no prices, setup fees or revenue splits are stored or shown.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, BeforeValidator, Field
from sqlalchemy import exists, insert, select, update
from sqlalchemy.exc import IntegrityError

from app.gateway import service_onboarding as plan_parser
from app.gateway import service_tiers
from app.gateway.authz import require_entitlement, require_permission
from app.gateway.deps import get_scheduled_task_repo
from app.gateway.routers.workspace_branding import _shared_membership
from app.gateway.routers.workspaces import _session_actor, _session_factory
from deerflow.persistence.organizations.model import OrganizationMemberRow, OrganizationRow
from deerflow.persistence.organizations.service import SERVICE_TIERS, WorkspaceServiceSettingsRow
from deerflow.persistence.user.model import UserRow
from deerflow.runtime.user_context import get_storage_context
from deerflow.scheduler.schedules import next_run_at as compute_next_run_at
from deerflow.scheduler.schedules import validate_timezone

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])
onboarding_router = APIRouter(prefix="/api/onboarding", tags=["workspaces"])

_EDIT_ROLES = ("owner", "admin")
#: Who can be credited as the seller: a team member, never a client.
_SELLER_ROLES = ("owner", "admin", "member")
_STALE = "Service settings changed since they were opened. Reload and try again."
MAX_BOOKING_URL = 512
MAX_WORKSPACE_NAME = 120
_DEFAULT_ASSISTANT_ID = "lead_agent"


def _strip(value: object) -> object:
    return value.strip() if isinstance(value, str) else value


Stripped = Annotated[str | None, BeforeValidator(_strip)]


class ServiceSettingsResponse(BaseModel):
    workspace_id: str
    workspace_name: str
    service_tier: str | None = None
    booking_url: str | None = None
    sold_by_user_id: str | None = None
    check_in_task_id: str | None = None
    onboarding: dict[str, Any] | None = None
    version: int = 0
    can_edit: bool = False
    tiers: list[str] = Field(default_factory=lambda: list(SERVICE_TIERS))


class ServiceSettingsUpdate(BaseModel):
    service_tier: Stripped = Field(default=None, max_length=16)
    booking_url: Stripped = Field(default=None, max_length=MAX_BOOKING_URL + 1)
    sold_by_user_id: Stripped = Field(default=None, max_length=64)
    expected_version: int = Field(ge=0)


class ContractText(BaseModel):
    contract_text: str = Field(min_length=1, max_length=plan_parser.MAX_CONTRACT_CHARS)


class PlanItemIn(BaseModel):
    title: str = Field(min_length=1, max_length=400)
    cadence: str = Field(max_length=32)
    kind: str | None = Field(default=None, max_length=32)


class OnboardingApply(ContractText):
    expected_version: int = Field(ge=0)
    workspace_name: Stripped = Field(default=None, max_length=MAX_WORKSPACE_NAME + 1)
    # The reviewed plan from the preview step. Omitted: parse the text as-is.
    items: list[PlanItemIn] | None = Field(default=None, max_length=plan_parser.MAX_PLAN_ITEMS)
    timezone: str = Field(default="America/New_York", max_length=64)


def _require_enabled() -> None:
    if not service_tiers.service_tiers_enabled():
        raise HTTPException(status_code=404, detail="Not found")


async def _team_membership(session, actor_id: str, workspace_id: str):
    active = await _shared_membership(session, actor_id, workspace_id)
    if active.role == "client":
        raise HTTPException(status_code=404, detail="Workspace not found")
    return active


def _require_editor(active) -> None:
    if active.role not in _EDIT_ROLES:
        raise HTTPException(status_code=403, detail="Workspace owner or admin permission required")


def _response(active, row: WorkspaceServiceSettingsRow | None, *, can_edit: bool, name: str | None = None) -> ServiceSettingsResponse:
    return ServiceSettingsResponse(
        workspace_id=active.id,
        workspace_name=name or active.name,
        service_tier=row.service_tier if row is not None else None,
        booking_url=row.booking_url if row is not None else None,
        sold_by_user_id=row.sold_by_user_id if row is not None else None,
        check_in_task_id=row.check_in_task_id if row is not None else None,
        onboarding=row.onboarding if row is not None else None,
        version=row.version if row is not None else 0,
        can_edit=can_edit,
    )


def _validated_tier(value: str | None) -> str | None:
    if value in (None, ""):
        return None
    if value not in SERVICE_TIERS:
        raise HTTPException(status_code=422, detail="Service tier must be one of " + ", ".join(SERVICE_TIERS))
    return value


def _validated_booking_url(value: str | None) -> str | None:
    """https only, with a host and no embedded sign-in details."""
    if value in (None, ""):
        return None
    if len(value) > MAX_BOOKING_URL:
        raise HTTPException(status_code=422, detail="The booking link is too long")
    try:
        parts = urlsplit(value)
    except ValueError:
        raise HTTPException(status_code=422, detail="The booking link must be a full https:// address") from None
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or any(ch.isspace() for ch in value):
        raise HTTPException(status_code=422, detail="The booking link must be a full https:// address")
    return value


async def _validated_seller(session, workspace_id: str, user_id: str | None) -> str | None:
    if user_id in (None, ""):
        return None
    found = await session.scalar(
        select(OrganizationMemberRow.user_id).where(
            OrganizationMemberRow.organization_id == workspace_id,
            OrganizationMemberRow.user_id == user_id,
            OrganizationMemberRow.status == "active",
            OrganizationMemberRow.role.in_(_SELLER_ROLES),
            ~exists().where(UserRow.id == user_id, UserRow.disabled_at.is_not(None)),
        )
    )
    if found is None:
        raise HTTPException(status_code=422, detail="The seller must be an active team member of this workspace")
    return user_id


async def _write(session, workspace_id: str, expected: int, actor_id: str, values: dict[str, Any]) -> WorkspaceServiceSettingsRow:
    """Compare-and-set write, same contract as workspace branding: stale is 412."""
    now = datetime.now(UTC)
    values = {**values, "updated_by": actor_id, "updated_at": now}
    if expected == 0:
        try:
            await session.execute(insert(WorkspaceServiceSettingsRow).values(organization_id=workspace_id, version=1, created_at=now, **values))
            await session.commit()
        except IntegrityError:
            await session.rollback()
            raise HTTPException(status_code=412, detail=_STALE) from None
    else:
        result = await session.execute(update(WorkspaceServiceSettingsRow).where(WorkspaceServiceSettingsRow.organization_id == workspace_id, WorkspaceServiceSettingsRow.version == expected).values(version=expected + 1, **values))
        await session.commit()
        if result.rowcount != 1:
            raise HTTPException(status_code=412, detail=_STALE)
    row = await session.get(WorkspaceServiceSettingsRow, workspace_id, populate_existing=True)
    assert row is not None
    return row


@router.get("/{workspace_id}/service", response_model=ServiceSettingsResponse)
async def get_service_settings(workspace_id: str, request: Request) -> ServiceSettingsResponse:
    _require_enabled()
    actor = _session_actor(request)
    async with _session_factory()() as session:
        active = await _team_membership(session, str(actor.id), workspace_id)
        row = await session.get(WorkspaceServiceSettingsRow, active.id)
        return _response(active, row, can_edit=active.role in _EDIT_ROLES)


@router.put("/{workspace_id}/service", response_model=ServiceSettingsResponse)
async def update_service_settings(workspace_id: str, body: ServiceSettingsUpdate, request: Request) -> ServiceSettingsResponse:
    _require_enabled()
    actor = _session_actor(request)
    actor_id = str(actor.id)
    async with _session_factory()() as session:
        active = await _team_membership(session, actor_id, workspace_id)
        _require_editor(active)
        # Validate everything before the write so a refused body never bumps the version.
        values = {
            "service_tier": _validated_tier(body.service_tier),
            "booking_url": _validated_booking_url(body.booking_url),
            "sold_by_user_id": await _validated_seller(session, active.id, body.sold_by_user_id),
        }
        row = await _write(session, active.id, body.expected_version, actor_id, values)
        return _response(active, row, can_edit=True)


def _plan_view(items: list[plan_parser.PlanItem]) -> dict[str, Any]:
    return {
        "items": [item.as_dict() for item in items],
        "recurring": sum(1 for item in items if item.cron),
        "one_time": sum(1 for item in items if not item.cron),
        "cadences": [{"id": key, "label": label} for key, (label, _cron) in plan_parser.CADENCES.items()],
        "kinds": [{"id": key, "label": label} for key, label in plan_parser.KINDS.items()],
    }


@onboarding_router.post("/{workspace_id}/preview")
async def preview_onboarding(workspace_id: str, body: ContractText, request: Request) -> dict[str, Any]:
    """Show the plan a contract would create. Reads nothing but membership; writes nothing."""
    _require_enabled()
    actor = _session_actor(request)
    async with _session_factory()() as session:
        active = await _team_membership(session, str(actor.id), workspace_id)
        _require_editor(active)
    return _plan_view(plan_parser.parse_contract(body.contract_text))


def _reviewed_items(body: OnboardingApply) -> list[plan_parser.PlanItem]:
    if body.items is None:
        return plan_parser.parse_contract(body.contract_text)
    try:
        return [plan_parser.make_item(item.title, item.cadence, item.kind) for item in body.items]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


async def _create_paused_task(repo, *, owner: str, actor_id: str, title: str, prompt: str, cron: str, timezone: str) -> str:
    spec = {"cron": cron}
    task = await repo.create(
        task_id=f"task-{uuid.uuid4().hex}",
        user_id=owner,
        thread_id=None,
        context_mode="fresh_thread_per_run",
        assistant_id=_DEFAULT_ASSISTANT_ID,
        title=title[:200],
        prompt=prompt,
        schedule_type="cron",
        schedule_spec=spec,
        timezone=timezone,
        next_run_at=compute_next_run_at("cron", spec, timezone, now=datetime.now(UTC)),
        # The acting person, never the storage principal, owns the launch delegation.
        delegation_owner_user_id=actor_id,
        status="paused",
    )
    return str(task["id"])


async def _discard_tasks(repo, owner: str, task_ids: list[str]) -> None:
    for task_id in task_ids:
        try:
            await repo.delete_with_queue_cancellation(task_id, user_id=owner, error="onboarding was not applied", now=datetime.now(UTC))
        except Exception:  # best effort: a paused task never runs on its own
            continue


@onboarding_router.post("/{workspace_id}/apply", response_model=ServiceSettingsResponse)
@require_permission("threads", "write")
@require_permission("runs", "create")
@require_entitlement("runs.create")
async def apply_onboarding(workspace_id: str, body: OnboardingApply, request: Request) -> ServiceSettingsResponse:
    """Name the workspace, store the plan and create its tasks paused.

    Applies once. Tasks are created first and removed again if the settings
    write loses its compare-and-set, so a double submit leaves one plan.
    """
    _require_enabled()
    actor = _session_actor(request)
    actor_id = str(actor.id)
    context = get_storage_context()
    if context is None or context.organization_id != workspace_id:
        raise HTTPException(status_code=409, detail="Switch to this workspace first, then run onboarding.")
    try:
        validate_timezone(body.timezone)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    items = _reviewed_items(body)
    if not items:
        raise HTTPException(status_code=422, detail="No deliverables found. Put one per line, for example: 4 blog posts per month.")
    new_name = body.workspace_name
    if new_name is not None and not (1 <= len(new_name) <= MAX_WORKSPACE_NAME):
        raise HTTPException(status_code=422, detail=f"The workspace name must be 1 to {MAX_WORKSPACE_NAME} characters")

    repo = get_scheduled_task_repo(request)
    owner = context.storage_user_id
    async with _session_factory()() as session:
        active = await _team_membership(session, actor_id, workspace_id)
        _require_editor(active)
        current = await session.get(WorkspaceServiceSettingsRow, active.id)
        if (current.version if current is not None else 0) != body.expected_version:
            raise HTTPException(status_code=412, detail=_STALE)
        if current is not None and (current.onboarding or {}).get("applied_at"):
            raise HTTPException(status_code=409, detail="Onboarding was already applied. Its tasks are in Scheduled tasks.")
        tier = current.service_tier if current is not None and current.service_tier in SERVICE_TIERS else None
        seller = (current.sold_by_user_id if current is not None else None) or actor_id
        workspace_name = new_name or active.name

    created: list[str] = []
    plan_items: list[dict[str, Any]] = []
    check_in_task_id: str | None = None
    try:
        for item in items:
            entry = item.as_dict()
            if item.cron:
                prompt = plan_parser.task_prompt(item, workspace_name=workspace_name, tier=tier)
                entry["task_id"] = await _create_paused_task(repo, owner=owner, actor_id=actor_id, title=item.title, prompt=prompt, cron=item.cron, timezone=body.timezone)
                created.append(entry["task_id"])
            plan_items.append(entry)
        if seller == actor_id:
            # Only the seller can own their own check-in: granting a launch
            # delegation for someone else would create access for them.
            check_in_task_id = await _create_paused_task(
                repo,
                owner=owner,
                actor_id=actor_id,
                title=f"Monthly check-in: {workspace_name}",
                prompt=plan_parser.check_in_prompt(workspace_name=workspace_name, seller_name="the seller"),
                cron=plan_parser.CADENCES["monthly"][1] or "0 9 1 * *",
                timezone=body.timezone,
            )
            created.append(check_in_task_id)
    except HTTPException:
        await _discard_tasks(repo, owner, created)
        raise
    except Exception as exc:
        await _discard_tasks(repo, owner, created)
        raise HTTPException(status_code=503, detail="The plan's tasks could not be created. Nothing was saved.") from exc

    onboarding = {
        "applied_at": datetime.now(UTC).isoformat(),
        "applied_by": actor_id,
        "contract_sha256": plan_parser.contract_digest(body.contract_text),
        "timezone": body.timezone,
        "items": plan_items,
        "tasks_paused": True,
    }
    async with _session_factory()() as session:
        try:
            row = await _write(
                session,
                workspace_id,
                body.expected_version,
                actor_id,
                {
                    "service_tier": current.service_tier if current is not None else None,
                    "booking_url": current.booking_url if current is not None else None,
                    "sold_by_user_id": seller,
                    "check_in_task_id": check_in_task_id,
                    "onboarding": onboarding,
                },
            )
        except HTTPException:
            await _discard_tasks(repo, owner, created)
            raise
        if new_name is not None and new_name != active.name:
            await session.execute(update(OrganizationRow).where(OrganizationRow.id == workspace_id).values(name=new_name, updated_at=datetime.now(UTC)))
            await session.commit()
        return _response(active, row, can_edit=True, name=workspace_name)
