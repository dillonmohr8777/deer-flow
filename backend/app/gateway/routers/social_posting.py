"""Social posting inside MomoBot: workspace settings, the post list and the public page.

Approved ``social_post`` actions publish through ``SocialPostAdapter`` below,
which the approvals router calls only for the reviewer that won the
pending->approved compare-and-set. Posts go live on the workspace's own
MomoBot-hosted page; nothing is sent to an outside network.

While the global ``social_posting.enabled`` flag is off every route here
answers 404. While a workspace's own switch is off its page and post list
answer 404 too; only its owners and admins still see the settings, so they can
turn it on.
"""

from __future__ import annotations

import html
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.gateway.approval_adapters import register_adapter
from app.gateway.authz import require_permission
from app.gateway.deps import get_current_user_from_request, record_audit_event
from app.gateway.routers.clients import _is_active_org_admin
from deerflow.approvals import AdapterOutcome
from deerflow.persistence.approvals.model import PendingActionRow
from deerflow.persistence.organizations.branding import OrganizationBrandingRow
from deerflow.persistence.organizations.model import OrganizationRow
from deerflow.runtime.user_context import resolve_organization_id
from deerflow.social import ACTION_TYPE, OWN_PAGE_LABEL, global_enabled, is_valid_slug, load_settings, page_url, publish_approved, published_posts, save_settings, settings_for_slug

router = APIRouter(prefix="/api/social", tags=["social-posting"])
public_router = APIRouter(prefix="/api/public/social", tags=["social-posting"])

STATUS_LABELS = {"pending": "Waiting for approval", "approved": "Publishing", "executed": "Published", "failed": "Failed", "rejected": "Rejected"}


def _sf():
    from deerflow.persistence.engine import get_session_factory

    factory = get_session_factory()
    if factory is None:
        raise HTTPException(503, "Social posting requires persistent storage")
    return factory


def _unavailable() -> HTTPException:
    return HTTPException(404, "Not found")


def _require_global() -> None:
    if not global_enabled():
        raise _unavailable()


async def business_name(session_factory, organization_id: str) -> str:
    """The workspace's display name: its branding name, else the workspace name."""
    async with session_factory() as session:
        branding = await session.get(OrganizationBrandingRow, organization_id)
        if branding is not None and branding.brand_name:
            return branding.brand_name
        org = await session.get(OrganizationRow, organization_id)
        return org.name if org is not None else ""


class SocialSettingsResponse(BaseModel):
    enabled: bool
    public_url: str | None
    can_manage: bool
    business_name: str
    appears_on: str = OWN_PAGE_LABEL


class SocialSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None


class SocialPostItem(BaseModel):
    id: str
    status: str
    status_label: str
    text: str
    link: str | None
    created_at: str | None
    decided_at: str | None
    executed_at: str | None
    live_url: str | None
    error: str | None


class SocialPostList(BaseModel):
    page_url: str | None
    items: list[SocialPostItem]


async def _settings_response(sf, organization_id: str, actor: str) -> SocialSettingsResponse:
    settings = await load_settings(sf, organization_id)
    return SocialSettingsResponse(
        enabled=settings.enabled,
        public_url=page_url(settings.public_slug) if settings.live else None,
        can_manage=await _is_active_org_admin(actor),
        business_name=await business_name(sf, organization_id),
    )


@router.get("/settings", response_model=SocialSettingsResponse)
@require_permission("approvals", "read")
async def get_social_settings(request: Request) -> SocialSettingsResponse:
    _require_global()
    organization_id = resolve_organization_id()
    if not organization_id:
        raise _unavailable()
    actor = str((await get_current_user_from_request(request)).id)
    out = await _settings_response(_sf(), organization_id, actor)
    if not out.enabled and not out.can_manage:
        raise _unavailable()
    return out


@router.put("/settings", response_model=SocialSettingsResponse)
@require_permission("approvals", "write")
async def update_social_settings(body: SocialSettingsUpdate, request: Request) -> SocialSettingsResponse:
    _require_global()
    organization_id = resolve_organization_id()
    if not organization_id:
        raise _unavailable()
    actor = str((await get_current_user_from_request(request)).id)
    if not await _is_active_org_admin(actor):
        raise HTTPException(403, "Only a workspace owner or admin can change social posting")
    sf = _sf()
    await save_settings(sf, organization_id, actor_user_id=actor, business_name=await business_name(sf, organization_id), enabled=body.enabled)
    await record_audit_event(
        request,
        action="social_posting.settings_updated",
        outcome="success",
        actor_user_id=actor,
        organization_id=organization_id,
        target_type="workspace_social_settings",
        target_id=organization_id,
        details=body.model_dump(exclude_none=True),
    )
    return await _settings_response(sf, organization_id, actor)


def _iso(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else value


@router.get("/posts", response_model=SocialPostList)
@require_permission("approvals", "read")
async def list_social_posts(request: Request) -> SocialPostList:
    _require_global()
    organization_id = resolve_organization_id()
    if not organization_id:
        raise _unavailable()
    sf = _sf()
    settings = await load_settings(sf, organization_id)
    if not settings.live:
        raise _unavailable()
    async with sf() as session:
        rows = await session.scalars(select(PendingActionRow).where(PendingActionRow.organization_id == organization_id, PendingActionRow.action_type == ACTION_TYPE).order_by(PendingActionRow.created_at.desc()).limit(100))
        actions = list(rows)
    items = []
    for row in actions:
        payload = row.payload if isinstance(row.payload, dict) else {}
        result = row.execution_result if isinstance(row.execution_result, dict) else {}
        items.append(
            SocialPostItem(
                id=row.id,
                status=row.status,
                status_label=STATUS_LABELS.get(row.status, row.status),
                text=str(payload.get("text") or ""),
                link=payload.get("link") or None,
                created_at=_iso(row.created_at),
                decided_at=_iso(row.decided_at),
                executed_at=_iso(row.executed_at),
                live_url=result.get("live_url") if row.status == "executed" else None,
                error=row.error,
            )
        )
    return SocialPostList(page_url=page_url(settings.public_slug), items=items)


_PAGE_HEADERS = {
    "X-Robots-Tag": "noindex, nofollow",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "public, max-age=60",
}

_PAGE_CSS = (
    "body{margin:0;background:#f7f7f5;color:#1b1b1b;font:16px/1.55 system-ui,-apple-system,'Segoe UI',sans-serif}"
    "main{max-width:640px;margin:0 auto;padding:40px 20px 64px}"
    "h1{font-size:28px;line-height:1.2;margin:0 0 4px}"
    ".sub{color:#5c5c5c;margin:0 0 32px;font-size:14px}"
    "article{background:#fff;border:1px solid #e4e4e0;border-radius:12px;padding:20px;margin:0 0 16px}"
    "article p{margin:0;white-space:pre-wrap;overflow-wrap:anywhere}"
    "article a{display:inline-block;margin-top:12px;color:#0b57d0;overflow-wrap:anywhere}"
    "time{display:block;margin-top:12px;color:#6b6b6b;font-size:13px}"
    ".empty{color:#5c5c5c}"
    "@media (prefers-color-scheme:dark){body{background:#141414;color:#ececec}article{background:#1d1d1d;border-color:#2e2e2e}.sub,.empty,time{color:#a3a3a3}article a{color:#8ab4f8}}"
)


def render_page(name: str, posts: list) -> str:
    """Escaped, script-free HTML for one workspace page. Newest post first."""
    title = html.escape(name or "Updates")
    cards = []
    for post in posts:
        link = f'<a href="{html.escape(post.link, quote=True)}" rel="nofollow noopener ugc" target="_blank">{html.escape(post.link)}</a>' if post.link else ""
        when = post.published_at
        stamp = f'<time datetime="{html.escape(when.isoformat(), quote=True)}">{html.escape(when.strftime("%b %d, %Y"))}</time>' if isinstance(when, datetime) else ""
        cards.append(f"<article><p>{html.escape(post.text)}</p>{link}{stamp}</article>")
    body = "".join(cards) or '<p class="empty">No posts yet.</p>'
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="robots" content="noindex, nofollow">'
        f"<title>{title}</title><style>{_PAGE_CSS}</style></head>"
        f'<body><main><h1>{title}</h1><p class="sub">Latest updates</p>{body}</main></body></html>'
    )


@public_router.get("/{slug}", response_class=HTMLResponse, include_in_schema=False)
async def public_social_page(slug: str) -> HTMLResponse:
    """Read-only, noindex page of one workspace's published posts. 404 unless both switches are on."""
    if not global_enabled() or not is_valid_slug(slug):
        raise _unavailable()
    sf = _sf()
    settings = await settings_for_slug(sf, slug)
    if settings is None or not settings.live:
        raise _unavailable()
    posts = await published_posts(sf, settings.organization_id)
    name = await business_name(sf, settings.organization_id)
    return HTMLResponse(render_page(name, posts), headers=_PAGE_HEADERS)


class SocialPostAdapter:
    """Publishes an approved ``social_post`` on the active workspace's own MomoBot page."""

    async def execute(self, action: dict[str, Any]) -> AdapterOutcome:
        organization_id = resolve_organization_id()
        if not organization_id or action.get("organization_id") != organization_id:
            return AdapterOutcome("failed", error="Workspace no longer available")
        return await publish_approved(_sf(), action)


register_adapter(ACTION_TYPE, SocialPostAdapter())
