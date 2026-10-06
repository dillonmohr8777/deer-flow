"""ORM model for CEO Desk daily digests (queue item e14).

Each row is one generated digest for an organization -- a durable record of
"what shipped, what's stuck, what needs my yes" at that point in time, so
``GET /api/ceo/digest`` can show the most recent one and the scheduled sweep
(``deerflow.ceo_desk.digest.is_digest_due``) can tell whether today's is
already done without redrafting it. Organization-scoped like
``AgentSeatRow``/``BoardThreadRow`` (no DB-level foreign key, same "no FK by
design" convention used throughout this package).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base


def _utc_now() -> datetime:
    return datetime.now(UTC)


class CeoDeskDigestRow(Base):
    __tablename__ = "ceo_desk_digests"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    digest_text: Mapped[str] = mapped_column(Text, default="")
    shipped_count: Mapped[int] = mapped_column(Integer, default=0)
    stuck_count: Mapped[int] = mapped_column(Integer, default=0)
    needs_my_yes_drafts: Mapped[int] = mapped_column(Integer, default=0)
    needs_my_yes_ratifications: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, index=True)
