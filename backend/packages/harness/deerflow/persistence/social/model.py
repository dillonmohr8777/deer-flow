"""ORM models for social posting inside MomoBot.

``SocialPostRow`` is the receipt of one approved post on a workspace's own
MomoBot page: a row exists only once the post is live, and ``approval_id`` is
unique, so one approval can never publish twice. Pending, rejected and failed
posts live in ``pending_actions`` like every other approval.

``WorkspaceSocialSettingsRow`` holds the per-workspace switch (off by default),
the demo-only auto-publish setting and the public page slug. The slug is random
and never derived from an internal id. ``organization_id`` is server-owned with
no DB-level foreign key, matching the rest of this package.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Index, String, Text, false
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base


def _utc_now() -> datetime:
    return datetime.now(UTC)


class WorkspaceSocialSettingsRow(Base):
    __tablename__ = "workspace_social_settings"

    organization_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    public_slug: Mapped[str | None] = mapped_column(String(80), unique=True, nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


class SocialPostRow(Base):
    __tablename__ = "social_posts"
    __table_args__ = (Index("ix_social_posts_org_published", "organization_id", "published_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(64))
    approval_id: Mapped[str] = mapped_column(String(64), unique=True)
    text: Mapped[str] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    published_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
