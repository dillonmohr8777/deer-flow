"""ORM model for the M4 entitlement gate (``e6 m4-entitlements``).

Design: ``docs/momo-week/m4-entitlement.md`` (from task ``c2``). One row per
``(organization_id, key)``. A gate key (``console.read``, ``runs.create``,
``runs.cancel``, ``agents.manage``, ``schedules.manage``) carries no
``limit_value`` — the row's existence plus ``status="active"`` is the grant.
A limit key (``projects.max``, ``workflows.max``, ``brands.max``,
``repair_minutes.monthly``) carries ``limit_value``. No FK by design, matching
every other organization-scoped table in this schema (see
``board/model.py``, ``clients/model.py``).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base


def _utc_now() -> datetime:
    return datetime.now(UTC)


class OrganizationEntitlementRow(Base):
    __tablename__ = "organization_entitlements"

    organization_id: Mapped[str] = mapped_column(String(64), primary_key=True, index=True)
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    limit_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="manual")
    status: Mapped[str] = mapped_column(String(32), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, onupdate=_utc_now)
