"""ORM models for the Momentum team board: staff-only channels and messages.

Deliberately separate from ``board_threads``/``board_messages``. The Momo
Board is client-facing (per-client threads, drafts, approvals), and its
router skips the per-client check for a thread with no ``client_id``. Team
chatter living in those tables would inherit that gap, so staff channels get
their own tables and their own router, and nothing client-facing can reach
them. ``organization_id`` is server-owned and carries no DB-level foreign
key, the same convention as ``board/model.py`` and ``clients/model.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base


def _utc_now() -> datetime:
    return datetime.now(UTC)


# Channels every Momentum workspace starts with, in sidebar order.
DEFAULT_TEAM_CHANNELS: tuple[tuple[str, str, str], ...] = (
    ("general", "General", "Anything the whole team should see."),
    ("sales", "Sales", "Leads, pitches and pipeline."),
    ("fulfillment", "Fulfillment", "Client delivery, handoffs and deadlines."),
    ("ai-tech-news", "AI tech news", "New tools, what we tried, what worked."),
    ("wins", "Wins", "Client results and good news worth repeating."),
)


class TeamChannelRow(Base):
    __tablename__ = "team_channels"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    slug: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(128))
    topic: Mapped[str] = mapped_column(String(255), default="")
    created_by_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, onupdate=_utc_now)

    __table_args__ = (UniqueConstraint("organization_id", "slug", name="uq_team_channels_org_slug"),)


class TeamMessageRow(Base):
    __tablename__ = "team_messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    channel_id: Mapped[str] = mapped_column(String(64), index=True)
    author_user_id: Mapped[str] = mapped_column(String(64), index=True)
    body: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, index=True)
