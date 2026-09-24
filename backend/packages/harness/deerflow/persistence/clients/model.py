"""ORM models for the client roster (Momentum Phase 2 item 2).

``ClientRow`` is organization-owned, not user-owned -- like ``OrganizationRow``
itself, it carries no ``user_id``: a client belongs to the workspace, and
individual people are linked to it through ``ClientAssignmentRow`` rows.
``registry_id`` identifies the row in the external client-operations registry
(item 3's import target) and is unique per organization; NULL stays allowed
and distinct (no registry link yet).

``ClientAssignmentRow`` mirrors ``OrganizationMemberRow``'s composite-primary-key
shape: one row per ``(client_id, user_id)`` pair, so "unique per client+user"
is a schema invariant rather than an application-level check.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ClientRow(Base):
    __tablename__ = "clients"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    display_name: Mapped[str] = mapped_column(String(255))
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    email_domains: Mapped[list] = mapped_column(JSON, default=list)
    slack_channel_ids: Mapped[list] = mapped_column(JSON, default=list)
    registry_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, onupdate=_utc_now)

    __table_args__ = (UniqueConstraint("organization_id", "registry_id", name="uq_clients_org_registry_id"),)


class ClientAssignmentRow(Base):
    __tablename__ = "client_assignments"

    client_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), primary_key=True, index=True)
    organization_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    role: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, onupdate=_utc_now)
