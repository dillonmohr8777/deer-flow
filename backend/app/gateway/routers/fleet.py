"""Read-only fleet template catalog API.

Templates are curated, versioned files under ``fleet/templates/`` (see
``deerflow.fleet``), not database rows; there is nothing to scope by
organization here, unlike ``clients.py``. Stamping a template onto a client
lives on the client roster router (``POST /api/clients/{client_id}/agents``),
since that action *is* organization- and client-scoped.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.gateway.authz import require_permission
from deerflow.fleet import FleetTemplateError, load_fleet_templates

router = APIRouter(prefix="/api/fleet", tags=["fleet"])


class FleetTemplateSchedule(BaseModel):
    cron: str
    timezone: str


class FleetTemplateResponse(BaseModel):
    id: str
    version: str
    name: str
    description: str
    model: str
    skills: list[str]
    tool_groups: list[str]
    mcp_plugins: list[str]
    schedule: FleetTemplateSchedule
    acceptance_criteria: list[str]


class FleetTemplateListResponse(BaseModel):
    templates: list[FleetTemplateResponse]


def _to_response(template) -> FleetTemplateResponse:
    return FleetTemplateResponse(
        id=template.id,
        version=template.version,
        name=template.name,
        description=template.description,
        model=template.model,
        skills=template.skills,
        tool_groups=template.tool_groups,
        mcp_plugins=template.mcp_plugins,
        schedule=FleetTemplateSchedule(cron=template.schedule.cron, timezone=template.schedule.timezone),
        acceptance_criteria=template.acceptance_criteria,
    )


@router.get("/templates", response_model=FleetTemplateListResponse)
@require_permission("clients", "read")
async def list_fleet_templates(request: Request) -> FleetTemplateListResponse:
    """List the fleet template catalog (id, name, description, defaults, schedule)."""
    try:
        templates = await asyncio.to_thread(load_fleet_templates)
    except FleetTemplateError as exc:
        # A curated, operator-owned template library that fails to load is a
        # deployment misconfiguration; surface it plainly rather than
        # silently dropping the broken entry from the catalog.
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return FleetTemplateListResponse(templates=[_to_response(t) for t in templates])
