"""Required first-login onboarding for staff: role, daily tools, tool connections.

State lives in the owner-scoped preference rows (``user_preferences``), so it
survives devices and shows exactly once. Clients never reach this router: the
client route boundary denies it by default.

A tool counts as connected only through an existing per-user mechanism:
``google_ads``/``meta_ads`` through the user's own ads credentials file, and the
rest through an operator-configured MCP server whose ``user_auth`` block maps
this user to their own credential. Anything else is recorded as "requested"
(the UI shows "coming soon"), never as a fake success.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import select

from app.gateway.deps import get_current_user_from_request, require_admin_user
from app.gateway.people_profiles import PersonProfile, load_own_profile
from app.gateway.routers import user_preferences
from deerflow.persistence.user.model import UserPreferenceRow, UserRow
from deerflow.persistence.user.preferences import UserPreferencesRepository
from deerflow.runtime.user_context import get_effective_user_id

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/auth/onboarding", tags=["auth"])

# The common daily tools, pinned at the top of the step-2 catalog.
PINNED_TOOLS: dict[str, str] = {
    "slack": "Slack",
    "gmail": "Gmail",
    "google_calendar": "Google Calendar",
    "google_drive": "Google Drive",
    "hubspot": "HubSpot",
    "google_ads": "Google Ads",
    "meta_ads": "Meta Ads",
    "ga4": "GA4",
    "search_console": "Search Console",
}
# Operator-configured MCP servers with a user_auth block (see docs/MOMOBOT_ONBOARDING.md).
# Any other id is looked up as "<id>-user", then "<id>".
MCP_SERVER_FOR_TOOL: dict[str, str] = {
    "google_calendar": "google-calendar-user",
    "google_drive": "google-drive-user",
    "search_console": "search-console-user",
}
ADS_TOOLS = frozenset({"google_ads", "meta_ads"})
ONBOARDED_ROLES = frozenset({"user", "exec", "admin"})

PROFILE_KEY = "onboarding_profile"
TOOLS_KEY = "daily_tools"
CONNECTIONS_KEY = "onboarding_connections"
COMPLETED_KEY = "onboarding_completed_at"

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class ProfileStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Text
    team: Text


ToolId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_.:-]{0,127}$")]


class ToolsStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tools: list[ToolId] = Field(max_length=200)
    other: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] = ""


class ConnectionStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["requested", "skipped"]


class CatalogEntry(BaseModel):
    id: str
    label: str
    group: str
    pinned: bool = False


class ToolState(BaseModel):
    id: str
    label: str
    # "shared": an enabled MCP server with no per-user auth, already usable by everyone.
    status: Literal["connected", "shared", "requested", "skipped", "pending"]
    available: bool


class OnboardingState(BaseModel):
    required: bool
    completed_at: str | None = None
    role: str = ""
    team: str = ""
    profile_found: bool = False
    clients: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    other: str = ""
    catalog: list[CatalogEntry] = Field(default_factory=list)
    connections: list[ToolState] = Field(default_factory=list)


def _repository() -> UserPreferencesRepository:
    return user_preferences._repository()


def _catalog() -> dict[str, CatalogEntry]:
    """Everything a person can say they use: pinned tools, the plugin catalog, configured MCP servers."""
    from deerflow.capabilities.catalog import load_catalog
    from deerflow.config.extensions_config import get_extensions_config

    entries = {tool: CatalogEntry(id=tool, label=label, group="Most used", pinned=True) for tool, label in PINNED_TOOLS.items()}
    try:
        manifests = load_catalog()
    except Exception:
        logger.warning("Plugin catalog unavailable for onboarding", exc_info=True)
        manifests = []
    for manifest in manifests:
        label = manifest.name.get("en-US") or manifest.name.get("en") or next(iter(manifest.name.values()), manifest.id)
        entries.setdefault(manifest.id, CatalogEntry(id=manifest.id, label=label, group=manifest.category.capitalize()))
    per_user = {_server_names(tool)[0] for tool in entries}
    for name in get_extensions_config().get_enabled_mcp_servers():
        if name not in per_user and name not in entries:
            entries[name] = CatalogEntry(id=name, label=name.replace("-", " ").replace("_", " ").title(), group="Connected to MomoBot")
    return entries


def _server_names(tool: str) -> tuple[str, str]:
    return MCP_SERVER_FOR_TOOL.get(tool, f"{tool.replace('_', '-')}-user"), tool


def _tool_state(entry: CatalogEntry, recorded: str | None, user_ids: set[str]) -> ToolState:
    status = None
    available = False
    if entry.id in ADS_TOOLS:
        from deerflow.community.ads.common import AdsToolError, load_credentials

        available = True
        try:
            load_credentials(entry.id)
            status = "connected"
        except AdsToolError:
            pass
    else:
        from deerflow.config.extensions_config import get_extensions_config

        servers = get_extensions_config().get_enabled_mcp_servers()
        for name in _server_names(entry.id):
            server = servers.get(name)
            if server is None:
                continue
            available = True
            if server.user_auth is not None and server.user_auth.enabled:
                status = "connected" if any(server.user_auth.users.get(uid) for uid in user_ids) else None
            else:
                status = "shared"
            break
    if status is None:
        status = recorded if recorded in {"requested", "skipped"} else "pending"
    return ToolState(id=entry.id, label=entry.label, status=status, available=available)


async def _context(request: Request, expected_user: str):
    owner = await user_preferences._owner(request, expected_user)
    user = await get_current_user_from_request(request)
    if getattr(user, "system_role", "user") not in ONBOARDED_ROLES:
        raise HTTPException(403, "Onboarding is for Momentum staff")
    return owner, user, await _repository().get(owner)


def _state(owner: str, user, stored: dict) -> OnboardingState:
    profile = load_own_profile(getattr(user, "email", None)) or PersonProfile()
    saved = stored.get(PROFILE_KEY) if isinstance(stored.get(PROFILE_KEY), dict) else {}
    tools_step = stored.get(TOOLS_KEY) if isinstance(stored.get(TOOLS_KEY), dict) else {}
    recorded = stored.get(CONNECTIONS_KEY) if isinstance(stored.get(CONNECTIONS_KEY), dict) else {}
    catalog = _catalog()
    chosen = [tool for tool in tools_step.get("tools", []) if tool in catalog]
    # Before step 2 the profile's tools pre-select the checklist.
    preselect = chosen if tools_step else [tool for tool in profile.tools if tool in catalog]
    user_ids = {owner, get_effective_user_id()}
    return OnboardingState(
        required=not stored.get(COMPLETED_KEY),
        completed_at=stored.get(COMPLETED_KEY),
        role=saved.get("role") or profile.role,
        team=saved.get("team") or profile.team,
        profile_found=profile != PersonProfile(),
        clients=profile.clients,
        tools=preselect,
        other=tools_step.get("other", ""),
        catalog=list(catalog.values()),
        connections=[_tool_state(catalog[tool], recorded.get(tool), user_ids) for tool in chosen],
    )


async def _seed_memory(profile: PersonProfile, role: str, team: str, tools: list[str], other: str) -> None:
    catalog = _catalog()
    facts = [f"Role at Momentum: {role}. Team: {team}."]
    if profile.clients:
        facts.append(f"Clients this person works on: {', '.join(profile.clients)}.")
    daily = [catalog[tool].label if tool in catalog else tool for tool in tools] + ([other] if other else [])
    if daily:
        facts.append(f"Tools this person uses every day: {', '.join(daily)}.")
    if profile.notes:
        facts.append(f"Working style: {profile.notes}")
    from deerflow.agents.memory import get_memory_manager

    manager = await asyncio.to_thread(get_memory_manager)
    user_id = get_effective_user_id()
    for content in facts:
        await asyncio.to_thread(manager.create_fact, content=content, category="context", confidence=0.9, user_id=user_id)


@router.get("", response_model=OnboardingState)
async def get_onboarding(request: Request, x_expected_user_id: str = Header(...)) -> OnboardingState:
    owner = await user_preferences._owner(request, x_expected_user_id)
    user = await get_current_user_from_request(request)
    if getattr(user, "system_role", "user") not in ONBOARDED_ROLES:
        return OnboardingState(required=False)
    return _state(owner, user, await _repository().get(owner))


@router.put("/profile", response_model=OnboardingState)
async def put_profile(body: ProfileStep, request: Request, x_expected_user_id: str = Header(...)) -> OnboardingState:
    owner, user, stored = await _context(request, x_expected_user_id)
    values = {PROFILE_KEY: body.model_dump()}
    await _repository().patch(owner, values)
    return _state(owner, user, {**stored, **values})


@router.put("/tools", response_model=OnboardingState)
async def put_tools(body: ToolsStep, request: Request, x_expected_user_id: str = Header(...)) -> OnboardingState:
    owner, user, stored = await _context(request, x_expected_user_id)
    if not stored.get(PROFILE_KEY):
        raise HTTPException(409, "Confirm your role and team first")
    if not body.tools and not body.other:
        raise HTTPException(422, "Pick at least one tool you use every day")
    unknown = sorted(set(body.tools) - set(_catalog()))
    if unknown:
        raise HTTPException(422, f"Unknown tools: {', '.join(unknown)}")
    values = {TOOLS_KEY: {"tools": list(dict.fromkeys(body.tools)), "other": body.other}}
    await _repository().patch(owner, values)
    return _state(owner, user, {**stored, **values})


@router.post("/connections/{tool}", response_model=OnboardingState)
async def record_connection(tool: ToolId, body: ConnectionStep, request: Request, x_expected_user_id: str = Header(...)) -> OnboardingState:
    owner, user, stored = await _context(request, x_expected_user_id)
    tools_step = stored.get(TOOLS_KEY) or {}
    if tool not in tools_step.get("tools", []):
        raise HTTPException(409, "Pick this tool in the daily tools step first")
    recorded = {**(stored.get(CONNECTIONS_KEY) or {}), tool: body.status}
    await _repository().patch(owner, {CONNECTIONS_KEY: recorded})
    return _state(owner, user, {**stored, CONNECTIONS_KEY: recorded})


@router.post("/complete", response_model=OnboardingState)
async def complete_onboarding(request: Request, x_expected_user_id: str = Header(...)) -> OnboardingState:
    owner, user, stored = await _context(request, x_expected_user_id)
    if stored.get(COMPLETED_KEY):
        return _state(owner, user, stored)
    saved, tools_step = stored.get(PROFILE_KEY), stored.get(TOOLS_KEY)
    if not saved or not tools_step:
        raise HTTPException(409, "Finish your role and daily tools first")
    # Tools the person moved past without choosing are recorded as skipped.
    recorded = {tool: "skipped" for tool in tools_step.get("tools", [])} | (stored.get(CONNECTIONS_KEY) or {})
    # Free-text tools are not in the catalog yet, so they are always a request.
    if tools_step.get("other"):
        recorded["other"] = "requested"
    # Easy mode on the fast chat mode (MODE_FOR_EXPERIENCE.easy in the frontend).
    values = {CONNECTIONS_KEY: recorded, COMPLETED_KEY: datetime.now(UTC).isoformat(timespec="seconds"), "experience_mode": "easy", "mode": "flash"}
    await _repository().patch(owner, values)
    profile = load_own_profile(getattr(user, "email", None)) or PersonProfile()
    try:
        await _seed_memory(profile, saved["role"], saved["team"], tools_step.get("tools", []), tools_step.get("other", ""))
    except Exception:
        # Memory is a convenience; onboarding stays complete either way.
        logger.warning("Onboarding memory seed failed for user %s", owner, exc_info=True)
    return _state(owner, user, {**stored, **values})


class ConnectionRequest(BaseModel):
    email: str
    tools: dict[str, str]
    other: str = ""
    completed_at: str | None = None


@router.get("/requests", response_model=list[ConnectionRequest])
async def list_connection_requests(request: Request) -> list[ConnectionRequest]:
    """Admin view: who asked for which tool, so an operator can map credentials."""
    await require_admin_user(request, detail="Admin privileges required to view onboarding requests")
    async with _repository().sessions() as session:
        rows = (
            await session.execute(
                select(UserRow.id, UserRow.email, UserPreferenceRow.key, UserPreferenceRow.value).join(UserPreferenceRow, UserPreferenceRow.user_id == UserRow.id).where(UserPreferenceRow.key.in_([CONNECTIONS_KEY, COMPLETED_KEY, TOOLS_KEY]))
            )
        ).all()
    by_user: dict[str, ConnectionRequest] = {}
    for user_id, email, key, value in rows:
        entry = by_user.setdefault(user_id, ConnectionRequest(email=email, tools={}))
        if key == CONNECTIONS_KEY and isinstance(value, dict):
            entry.tools = {tool: status for tool, status in value.items() if status == "requested"}
        elif key == COMPLETED_KEY:
            entry.completed_at = value
        elif key == TOOLS_KEY and isinstance(value, dict):
            entry.other = value.get("other", "")
    return sorted((entry for entry in by_user.values() if entry.tools), key=lambda entry: entry.email)
