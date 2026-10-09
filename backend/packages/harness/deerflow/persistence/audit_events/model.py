"""ORM model for the append-only ``audit_events`` table (SOC 2 controls).

Rows are inserted once and never updated or deleted by application code.
``details`` is a JSON blob and must never carry secrets: callers pass raw
values to :class:`AuditEventRepository.record`, which redacts before
insert -- see :mod:`deerflow.persistence.audit_events.redact`.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base


class AuditEventRow(Base):
    __tablename__ = "audit_events"

    __table_args__ = (
        Index("ix_audit_events_occurred_at", "occurred_at"),
        Index("ix_audit_events_action", "action"),
        Index("ix_audit_events_organization_id", "organization_id"),
        Index("ix_audit_events_actor_user_id", "actor_user_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    # Null actor means a system-initiated event (no authenticated caller).
    actor_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    organization_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Dotted string, e.g. "auth.login.succeeded".
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # "success" | "denied" | "failed"
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(256), nullable=True)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
