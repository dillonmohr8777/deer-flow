"""Shared-workspace branding persistence.

Deliberately a 1:1 side table rather than columns on ``organizations``.
``auth_middleware`` resolves ``active_organization_for_user()`` — which selects
``OrganizationRow`` — on every authenticated request, so a bounded logo column
on that row would be loaded on the hot auth path for every request. Keeping it
here leaves that path byte-identical.

A missing row is not an error: it means "no branding set" and reads fall back to
``organizations.name`` with the default treatment. Only shared workspaces
(``organizations.storage_user_id`` non-null) ever get a row; private
organizations keep their existing behavior untouched.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base

#: Treatments the server accepts. Mirrors the three options rendered by
#: ``workspace-appearance.tsx``; anything else is rejected rather than coerced.
WORKSPACE_TREATMENTS: tuple[str, ...] = ("classic", "current", "paper")
DEFAULT_TREATMENT = "current"


def _utc_now() -> datetime:
    return datetime.now(UTC)


class OrganizationBrandingRow(Base):
    __tablename__ = "organization_branding"

    organization_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # NULL means "inherit organizations.name" rather than "named empty".
    brand_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Bounded data URI only. Never a remote URL and never SVG; see the router's
    # validation, which re-checks magic bytes and decoded dimensions.
    logo_data_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    treatment: Mapped[str] = mapped_column(String(16), default=DEFAULT_TREATMENT)
    # Monotonic per workspace, including across a reset, so an optimistic
    # ``expected_version`` cannot be defeated by resetting and re-saving.
    version: Mapped[int] = mapped_column(Integer, default=1)
    # The acting person, never the workspace storage principal.
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, onupdate=_utc_now)
