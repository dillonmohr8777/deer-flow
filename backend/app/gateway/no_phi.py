"""Health-sector workspaces: the no-PHI flag.

No business associate agreement covers any service behind this stack, so a
workspace flagged ``no_phi`` must never receive patient health information.
The flag is admin-owned (``PUT /api/admin/organizations/{id}/no-phi`` or the
``no_phi.organization_slugs`` config list), never client-settable, and has
three effects here:

* every agent run in the workspace carries the ``no_phi`` context key, which the
  lead-agent prompt turns into a marketing-only guard;
* file uploads are refused (``require_uploads_allowed``);
* the client portal shows a persistent banner (``active_no_phi`` on
  ``GET /api/workspaces``).

A workspace is flagged when its own row, the canonical client it is bound to,
or the operator config says so. A project (or a thread in one) whose
``client_id`` is a flagged client is flagged too, whichever workspace the caller
is in, so agency-staff threads on a health client's project are covered. When a
workspace is named but its row cannot be found, or there is no database while the
operator's slug list is non-empty, the answer is "flagged"; lookup errors propagate
(fail closed). A call that names no workspace, project or thread (internal callers,
dev, tests), or a database-less setup with an empty slug list, is unflagged.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.gateway.deps import get_config
from deerflow.config.app_config import AppConfig, get_app_config
from deerflow.persistence.clients.model import ClientRow
from deerflow.persistence.engine import get_session_factory
from deerflow.persistence.organizations.model import OrganizationRow
from deerflow.persistence.projects.model import ProjectRow
from deerflow.persistence.thread_meta.model import ThreadMetaRow
from deerflow.runtime.user_context import resolve_organization_id

NO_PHI_CONTEXT_KEY = "no_phi"
_LOOKUP_TIMEOUT_SECONDS = 10.0
UPLOADS_BLOCKED_DETAIL = "File uploads are turned off in this workspace. Please don't share patient or health information here."


def operator_config() -> AppConfig | None:
    """The process config, or None when there is no config.yaml (a gateway can't boot without one; tests can)."""
    try:
        return get_app_config()
    except FileNotFoundError:
        return None


def configured_no_phi_slugs(app_config: AppConfig | None) -> frozenset[str]:
    section = getattr(app_config, "no_phi", None)
    return frozenset(slug.strip().lower() for slug in getattr(section, "organization_slugs", ()) if isinstance(slug, str) and slug.strip())


async def _project_client_id(session: AsyncSession, project_id: str | None, thread_id: str | None) -> str | None:
    """The client a project (or the project a thread belongs to) is linked to, if any."""
    if not project_id and thread_id:
        project_id = (await session.execute(select(ThreadMetaRow.project_id).where(ThreadMetaRow.thread_id == thread_id))).scalar_one_or_none()
    if not project_id:
        return None
    return (await session.execute(select(ProjectRow.client_id).where(ProjectRow.id == project_id))).scalar_one_or_none()


async def organization_is_no_phi(
    organization_id: str | None,
    app_config: AppConfig | None = None,
    *,
    project_id: str | None = None,
    thread_id: str | None = None,
) -> bool:
    """Bounded :func:`_organization_is_no_phi`: a lookup that stalls past the limit counts as flagged (fail closed)."""
    try:
        return await asyncio.wait_for(
            _organization_is_no_phi(organization_id, app_config, project_id=project_id, thread_id=thread_id),
            timeout=_LOOKUP_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        return True


async def _organization_is_no_phi(
    organization_id: str | None,
    app_config: AppConfig | None = None,
    *,
    project_id: str | None = None,
    thread_id: str | None = None,
) -> bool:
    """True when the workspace, or the client behind the project/thread, is flagged.

    The workspace is flagged by its row, its bound client, or the operator config's
    slug list. A named workspace with no row is flagged, and so is any workspace when
    there is no database but the slug list is non-empty: the guard fails closed.
    Project and thread lookups need the database and are skipped without one.
    """
    slugs = configured_no_phi_slugs(app_config or operator_config())
    factory = get_session_factory()
    if organization_id:
        if factory is None:
            # No database: only the operator's slug list can flag a workspace, and its slug can't be
            # resolved. If the list names anything, fail closed; if it is empty there is nothing to read.
            return bool(slugs)
        async with factory() as session:
            row = (await session.execute(select(OrganizationRow.slug, OrganizationRow.no_phi, ClientRow.no_phi).outerjoin(ClientRow, ClientRow.id == OrganizationRow.customer_client_id).where(OrganizationRow.id == organization_id))).first()
        if row is None:
            return True
        slug, org_flag, client_flag = row
        if bool(org_flag) or bool(client_flag) or str(slug).strip().lower() in slugs:
            return True
    if factory is None or not (project_id or thread_id):
        return False
    async with factory() as session:
        client_id = await _project_client_id(session, project_id, thread_id)
        if not client_id:
            return False
        project_client_flag = (await session.execute(select(ClientRow.no_phi).where(ClientRow.id == client_id))).scalar_one_or_none()
    return project_client_flag is None or bool(project_client_flag)


async def delegation_is_no_phi(delegation_id: str | None, app_config: AppConfig | None = None, *, thread_id: str | None = None) -> bool:
    """:func:`organization_is_no_phi` for a channel message, whose workspace is its connection's delegation.

    A delegation that is named but no longer resolves is flagged (the Gateway would refuse the run too).
    """
    organization_id = None
    if delegation_id:
        factory = get_session_factory()
        if factory is None:
            return True
        from deerflow.persistence.organizations.delegation import OrganizationDelegationRepository

        delegation = await OrganizationDelegationRepository(factory).resolve_delegation_by_id(delegation_id)
        if delegation is None:
            return True
        organization_id = delegation.organization.id
    return await organization_is_no_phi(organization_id, app_config, thread_id=thread_id)


async def apply_no_phi_policy(config: dict[str, Any], *, request: Any, app_config: AppConfig | None = None) -> None:
    """Stamp ``no_phi`` on the run config for a flagged workspace; always drop a caller-supplied value.

    The workspace is the one the gateway resolved for this request, never a request field.
    """
    organization_id = getattr(getattr(request, "state", None), "organization_id", None) or resolve_organization_id()
    sections = [section for section in (config.get("configurable"), config.get("context")) if isinstance(section, dict)]
    for section in sections:
        section.pop(NO_PHI_CONTEXT_KEY, None)
    thread_id = next((section.get("thread_id") for section in sections if isinstance(section.get("thread_id"), str)), None)
    if not await organization_is_no_phi(organization_id, app_config, thread_id=thread_id):
        return
    for name in ("context", "configurable"):
        section = config.setdefault(name, {})
        if isinstance(section, dict):
            section[NO_PHI_CONTEXT_KEY] = True


async def require_uploads_allowed(app_config: AppConfig | None = None, *, project_id: str | None = None, thread_id: str | None = None) -> None:
    """Raise 403 when the request's workspace, or the client of its project/thread, is no-PHI. Internal callers (no workspace) pass."""
    if await organization_is_no_phi(resolve_organization_id(), app_config, project_id=project_id, thread_id=thread_id):
        raise HTTPException(status_code=403, detail=UPLOADS_BLOCKED_DETAIL)


async def uploads_allowed(request: Request, config: AppConfig = Depends(get_config)) -> None:
    """Route dependency form of :func:`require_uploads_allowed`; reads ``project_id`` / ``thread_id`` from the path."""
    params = request.path_params
    await require_uploads_allowed(config, project_id=params.get("project_id"), thread_id=params.get("thread_id"))
