"""Workspace service tiers: who reviews MomoBot's drafts in each workspace.

Mac Frederick's three-tier model, behind ``service_tiers.enabled`` (off by
default). Tier names only; no prices, setup fees or revenue splits live in the
product.

* ``software``: the client is the reviewer. Drafts wait in the client's own
  portal inbox; the client approves them or asks for changes. Nothing waits on
  an account manager, and staff cannot publish over the client.
* ``am_assisted``: the assigned account manager (or a workspace owner/admin)
  reviews and publishes. The client only sees published replies.
* ``standard``: MomoBot stays internal. Review is the same as ``am_assisted``
  and the client's portal does not link to a client-facing MomoBot.

While the flag is off, or a workspace has no tier set, :func:`workspace_tier`
returns ``None`` without reading the database and every caller keeps the
original rule exactly: only an active owner or admin approves publication.

Every tier still needs a human decision. Nothing here publishes, posts or sends
anything by itself; portal publication stays a DB-only adapter behind the
pending-action compare-and-set.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from deerflow.persistence.board.model import BoardThreadRow
from deerflow.persistence.organizations.service import SERVICE_TIERS, WorkspaceServiceSettingsRow

logger = logging.getLogger(__name__)

#: Plain-language reasons. A business owner new to marketing reads these.
LEGACY_REASON = "An organization owner or admin must approve publication"
CLIENT_REVIEWS = "In this workspace the client approves drafts in their own inbox."
TEAM_REVIEWS = "Your account manager reviews this before it is published."
ACCOUNT_MANAGER_ONLY = "Only the assigned account manager or a workspace owner or admin can approve this."
WITHDRAW_ONLY_ADMIN = "Only a workspace owner or admin can withdraw a draft the client is reviewing."
STANDARD_NO_CHAT = "Your team is handling this request and will reply in this inbox."


def service_tiers_enabled() -> bool:
    """Config-only, read per call. Any doubt reads as off."""
    try:
        from deerflow.config.app_config import get_app_config

        section = getattr(get_app_config(), "service_tiers", None)
    except Exception:  # an unreadable config never turns the feature on
        return False
    return getattr(section, "enabled", False) is True


def _session_factory():
    from deerflow.persistence.engine import get_session_factory

    factory = get_session_factory()
    if factory is None:
        raise HTTPException(503, "Service settings require persistent storage")
    return factory


async def read_service_settings(organization_id: str) -> WorkspaceServiceSettingsRow | None:
    """The workspace's settings row, or ``None``. Callers check the flag first."""
    try:
        async with _session_factory()() as session:
            return await session.get(WorkspaceServiceSettingsRow, organization_id)
    except SQLAlchemyError:
        # Fail closed: a decision is refused rather than routed by a guess.
        logger.warning("service settings unreadable for workspace %s", organization_id, exc_info=True)
        raise HTTPException(503, "Service tier could not be read") from None


async def workspace_tier(organization_id: str | None) -> str | None:
    """The workspace's tier, or ``None`` (flag off, no row, or no tier set)."""
    if not organization_id or not service_tiers_enabled():
        return None
    row = await read_service_settings(organization_id)
    tier = row.service_tier if row is not None else None
    return tier if tier in SERVICE_TIERS else None


async def portal_thread_client(organization_id: str, thread_id: str) -> str | None:
    try:
        async with _session_factory()() as session:
            return await session.scalar(select(BoardThreadRow.client_id).where(BoardThreadRow.id == thread_id, BoardThreadRow.organization_id == organization_id))
    except SQLAlchemyError:
        raise HTTPException(503, "Conversation could not be read") from None


@dataclass(frozen=True)
class PortalReview:
    """Who may decide one portal draft. ``tier`` is ``None`` on the original rule."""

    tier: str | None
    can_approve: bool
    can_withdraw: bool
    reason: str | None


async def _is_assigned_account_manager(*, actor_id: str, organization_id: str, client_id: str | None) -> bool:
    if not client_id:
        return False
    from app.gateway.client_context import require_staff_client

    try:
        await require_staff_client(actor_id=actor_id, organization_id=organization_id, client_id=client_id)
    except HTTPException as exc:
        if exc.status_code == 404:
            return False
        raise
    return True


async def portal_review(*, actor_id: str, organization_id: str, client_id: str | None, admin: bool, external: bool) -> PortalReview:
    """Apply the workspace tier to one draft.

    ``admin`` is an active owner/admin who is not client-facing; ``external``
    is a client (system role or ``client_contact`` assignment). Callers have
    already proven the actor can load the conversation.
    """
    tier = await workspace_tier(organization_id)
    staff_admin = admin and not external
    if tier is None:
        return PortalReview(None, staff_admin, staff_admin, None if staff_admin else LEGACY_REASON)
    if tier == "software":
        if external:
            return PortalReview(tier, True, False, None)
        return PortalReview(tier, False, staff_admin, CLIENT_REVIEWS)
    # am_assisted and standard: the team reviews, the client never does.
    if external:
        return PortalReview(tier, False, False, TEAM_REVIEWS)
    allowed = staff_admin or await _is_assigned_account_manager(actor_id=actor_id, organization_id=organization_id, client_id=client_id)
    return PortalReview(tier, allowed, allowed, None if allowed else ACCOUNT_MANAGER_ONLY)
