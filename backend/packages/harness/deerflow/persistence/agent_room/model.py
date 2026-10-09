"""Owner-private append-only message stream for the MomoBot Agent Room."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base


class AgentRoomMessageRow(Base):
    __tablename__ = "agent_room_messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    author_kind: Mapped[str] = mapped_column(String(16))
    agent_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    agent_role: Mapped[str] = mapped_column(String(128), default="")
    message_type: Mapped[str] = mapped_column(String(24), default="update")
    body: Mapped[str] = mapped_column(Text)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True)

    __table_args__ = (Index("ix_agent_room_user_created", "user_id", "created_at", "id"),)
