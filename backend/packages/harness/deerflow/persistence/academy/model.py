"""ORM model for AI Academy progress: which lessons a staff member has finished.

One row per (organization, user, lesson). Lesson ids are stable strings from
``app.gateway.academy_content``; the content itself is code, not data, so
only completion is stored. ``organization_id`` is server-owned with no
DB-level foreign key, matching the rest of this package.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base


def _utc_now() -> datetime:
    return datetime.now(UTC)


class AcademyProgressRow(Base):
    __tablename__ = "academy_progress"

    organization_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), primary_key=True, index=True)
    lesson_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
