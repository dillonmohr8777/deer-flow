"""Per-workspace service settings (Mac's three service tiers).

A 1:1 side table keyed by ``organizations.id``, for the same reason as
``organization_branding``: ``OrganizationRow`` is loaded on every authenticated
request, so nothing here should widen that hot row.

A missing row, or a row whose ``service_tier`` is NULL, means "no tier set":
the workspace keeps the original review routing exactly (only an owner or
admin approves). Nothing in this table is read at all while the
``service_tiers.enabled`` config flag is off.

No prices, setup fees or revenue splits live here or anywhere else in the
product: tier names only.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base

#: ``software``: the client is the reviewer; drafts wait in the client's own
#: portal and nothing waits on an account manager.
#: ``am_assisted``: the assigned account manager reviews and publishes.
#: ``standard``: MomoBot is internal; no client-facing MomoBot is required.
SERVICE_TIERS: tuple[str, ...] = ("software", "am_assisted", "standard")


def _utc_now() -> datetime:
    return datetime.now(UTC)


class WorkspaceServiceSettingsRow(Base):
    __tablename__ = "workspace_service_settings"

    organization_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # NULL means "no tier set": original routing, unchanged.
    service_tier: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # The team member who sold the workspace (seller attribution only).
    sold_by_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # https only; shown to software-tier clients as "Book a call".
    booking_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # The seller's monthly check-in scheduled task, when one was created.
    check_in_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # The onboarding work plan: items, the scheduled task each created, the
    # contract text's SHA-256 (never the text) and when onboarding was applied.
    onboarding: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    # The acting person, never the workspace storage principal.
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, onupdate=_utc_now)
