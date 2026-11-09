"""Social posting inside MomoBot: the ``social_post`` approval type and its publish core.

An agent proposes a post (text, optional link). It is filed in the approvals
inbox as ``social_post`` with target ``momobot_page``: the workspace's own,
MomoBot-hosted public page. Approving it publishes it there exactly once; a
rejected post is never published; a post that cannot publish settles as
``failed``. Nothing here sends anything outside MomoBot.

Two switches, both off by default, gate everything: the global
``social_posting.enabled`` config flag and the per-workspace
``workspace_social_settings.enabled`` switch an owner or admin sets. While the
global flag is off no ``social_post`` row can be filed by any tool. Every post
needs an owner or admin's approval in the web inbox; nothing publishes on its
own. The page link is never taken from a proposal: the server computes it from
the workspace's slug whenever it is shown.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from deerflow.approvals import AdapterOutcome, InvalidPayloadError, register_action_type
from deerflow.persistence.social.model import SocialPostRow, WorkspaceSocialSettingsRow

ACTION_TYPE = "social_post"
TARGET_OWN_PAGE = "momobot_page"
OWN_PAGE_LABEL = "Your MomoBot page"
MAX_TEXT_CHARS = 3000
MAX_LINK_CHARS = 2048
PUBLIC_PATH_PREFIX = "/api/public/social/"
_PAYLOAD_KEYS = {"text", "link"}
_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def global_enabled() -> bool:
    """The global ``social_posting.enabled`` flag. Any config problem reads as off."""
    try:
        from deerflow.config.app_config import get_app_config

        return bool(get_app_config().social_posting.enabled)
    except Exception:
        return False


def public_base_url() -> str:
    try:
        from deerflow.config.app_config import get_app_config

        return (get_app_config().social_posting.public_base_url or "").rstrip("/")
    except Exception:
        return ""


def page_path(slug: str) -> str:
    return f"{PUBLIC_PATH_PREFIX}{slug}"


def page_url(slug: str) -> str:
    """Shareable link to a workspace page; relative to the gateway origin when no base URL is configured."""
    return f"{public_base_url()}{page_path(slug)}"


def make_slug(business_name: str | None) -> str:
    """Readable, unguessable slug: the business name plus random hex. Never derived from an internal id."""
    base = re.sub(r"[^a-z0-9]+", "-", (business_name or "").lower()).strip("-")[:40].strip("-") or "page"
    return f"{base}-{secrets.token_hex(8)}"


def is_valid_slug(slug: str) -> bool:
    return 0 < len(slug) <= 80 and bool(_SLUG_RE.fullmatch(slug))


def _clean_link(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise InvalidPayloadError("link must be a URL string")
    link = value.strip()
    if len(link) > MAX_LINK_CHARS or any(ch.isspace() for ch in link):
        raise InvalidPayloadError("link must be a single http(s) URL")
    try:
        parts = urlsplit(link)
    except ValueError as exc:
        raise InvalidPayloadError("link must be a valid http(s) URL") from exc
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise InvalidPayloadError("link must start with http:// or https://")
    return link


def clean_post(payload: dict[str, Any]) -> tuple[str, str | None]:
    """Return ``(text, link)`` of a valid post payload or raise ``InvalidPayloadError``."""
    if "page_url" in payload:
        raise InvalidPayloadError("page_url is set by MomoBot from the workspace page; leave it out")
    extra = set(payload) - _PAYLOAD_KEYS
    if extra:
        raise InvalidPayloadError(f"Unknown social post fields: {sorted(extra)}")
    text = payload.get("text")
    if not isinstance(text, str) or not text.strip():
        raise InvalidPayloadError("A social post needs text")
    if len(text) > MAX_TEXT_CHARS:
        raise InvalidPayloadError(f"Social post text is limited to {MAX_TEXT_CHARS} characters")
    return text.strip(), _clean_link(payload.get("link"))


def validate_social_payload(target: str, payload: dict[str, Any]) -> None:
    """Runs at propose and edit time for every tool, so the global flag also stops generic filing."""
    if not global_enabled():
        raise InvalidPayloadError("Social posting is not available on this MomoBot")
    if target != TARGET_OWN_PAGE:
        raise InvalidPayloadError("Social posts can only go to the workspace's own MomoBot page")
    clean_post(payload)


register_action_type(ACTION_TYPE, validate_social_payload)


@dataclass(frozen=True)
class WorkspaceSocial:
    organization_id: str
    enabled: bool
    public_slug: str | None

    @property
    def live(self) -> bool:
        """Posts are visible and publishable only while both switches are on and a page exists."""
        return self.enabled and bool(self.public_slug) and global_enabled()


def _snapshot(row: WorkspaceSocialSettingsRow | None, organization_id: str) -> WorkspaceSocial:
    if row is None:
        return WorkspaceSocial(organization_id, False, None)
    return WorkspaceSocial(row.organization_id, bool(row.enabled), row.public_slug)


async def load_settings(session_factory, organization_id: str) -> WorkspaceSocial:
    async with session_factory() as session:
        return _snapshot(await session.get(WorkspaceSocialSettingsRow, organization_id), organization_id)


async def live_page_url(session_factory, organization_id: str | None) -> str | None:
    """The workspace page link, computed from its slug; ``None`` unless the page is live."""
    if not organization_id:
        return None
    settings = await load_settings(session_factory, organization_id)
    return page_url(settings.public_slug) if settings.live and settings.public_slug else None


async def save_settings(
    session_factory,
    organization_id: str,
    *,
    actor_user_id: str,
    business_name: str | None,
    enabled: bool | None = None,
) -> WorkspaceSocial:
    """Upsert one workspace's settings. The public slug is minted on first enable and then kept stable."""
    now = datetime.now(UTC)
    async with session_factory() as session, session.begin():
        row = await session.get(WorkspaceSocialSettingsRow, organization_id)
        if row is None:
            row = WorkspaceSocialSettingsRow(organization_id=organization_id, enabled=False, created_at=now)
            session.add(row)
        if enabled is not None:
            row.enabled = enabled
        if row.enabled and not row.public_slug:
            row.public_slug = make_slug(business_name)
        row.updated_by = actor_user_id
        row.updated_at = now
        await session.flush()
        return _snapshot(row, organization_id)


def _receipt_id(action_id: str) -> str:
    return hashlib.sha256(f"social:{action_id}".encode()).hexdigest()[:32]


def _detail(post_id: str, slug: str) -> dict[str, Any]:
    return {"delivery": TARGET_OWN_PAGE, "post_id": post_id, "live_url": page_url(slug), "page_path": page_path(slug)}


async def publish_approved(session_factory, action: dict[str, Any]) -> AdapterOutcome:
    """Publish one approved ``social_post`` on its workspace page, exactly once.

    ``social_posts.approval_id`` is unique, so a retry or a racing second call
    returns the first receipt instead of publishing again.
    """
    if action.get("action_type") != ACTION_TYPE or action.get("target") != TARGET_OWN_PAGE:
        return AdapterOutcome("failed", error="Not a MomoBot page post")
    organization_id = action.get("organization_id")
    if not organization_id:
        return AdapterOutcome("failed", error="Workspace no longer available")
    try:
        text, link = clean_post(action.get("payload") or {})
    except InvalidPayloadError as exc:
        return AdapterOutcome("failed", error=str(exc))
    if not global_enabled():
        return AdapterOutcome("failed", error="Social posting is turned off on this MomoBot")
    post_id = _receipt_id(action["id"])
    async with session_factory() as session:
        settings = _snapshot(await session.get(WorkspaceSocialSettingsRow, organization_id), organization_id)
        if not settings.live:
            return AdapterOutcome("failed", error="Social posting is turned off for this workspace")
        existing = await session.scalar(select(SocialPostRow).where(SocialPostRow.approval_id == action["id"]))
        if existing is not None:
            return AdapterOutcome("executed", _detail(existing.id, settings.public_slug))
        session.add(SocialPostRow(id=post_id, organization_id=organization_id, approval_id=action["id"], text=text, link=link, published_by=action.get("decided_by"), published_at=datetime.now(UTC)))
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            existing = await session.scalar(select(SocialPostRow).where(SocialPostRow.approval_id == action["id"]))
            if existing is None:
                return AdapterOutcome("failed", error="Could not record the post")
            post_id = existing.id
    return AdapterOutcome("executed", _detail(post_id, settings.public_slug))


async def published_posts(session_factory, organization_id: str, *, limit: int = 50) -> list[SocialPostRow]:
    """Posts on the public page: published and not taken down, newest first."""
    async with session_factory() as session:
        rows = await session.scalars(select(SocialPostRow).where(SocialPostRow.organization_id == organization_id, SocialPostRow.unpublished_at.is_(None)).order_by(SocialPostRow.published_at.desc(), SocialPostRow.id.desc()).limit(limit))
        return list(rows)


async def settings_for_slug(session_factory, slug: str) -> WorkspaceSocial | None:
    async with session_factory() as session:
        row = await session.scalar(select(WorkspaceSocialSettingsRow).where(WorkspaceSocialSettingsRow.public_slug == slug))
        return _snapshot(row, row.organization_id) if row is not None else None


async def unpublish_post(session_factory, organization_id: str, approval_id: str, *, actor_user_id: str) -> datetime | None:
    """Take one published post off the workspace page. The row stays for the record.

    Returns when it was taken down (the first time, if already down), or ``None``
    when this workspace has no published post for ``approval_id``.
    """
    async with session_factory() as session, session.begin():
        post = await session.scalar(select(SocialPostRow).where(SocialPostRow.organization_id == organization_id, SocialPostRow.approval_id == approval_id))
        if post is None:
            return None
        if post.unpublished_at is None:
            post.unpublished_at = datetime.now(UTC)
            post.unpublished_by = actor_user_id
        return post.unpublished_at
