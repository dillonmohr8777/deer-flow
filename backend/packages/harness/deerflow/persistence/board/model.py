"""ORM models for the Momo Board (Workspace Phase 4 item b1).

``BoardThreadRow`` is organization- and client-scoped, matching ``ClientRow``:
``organization_id`` and ``client_id`` are server-owned (resolved from request
context, never taken from client input) and carry no DB-level foreign key,
the same "no FK by design" convention used throughout this package (see
``clients/model.py``, ``projects/model.py``). ``BoardMessageRow`` holds the
ordered message history of a thread, including Momo's drafted replies before
an owner approves and sends them.

``BoardThreadKind`` and ``BoardThreadStatus`` are the canonical vocabularies,
mirroring ``scheduled_tasks/model.py``'s ``ScheduledTaskRunStatus`` shape.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base


def _utc_now() -> datetime:
    return datetime.now(UTC)


class BoardThreadKind(StrEnum):
    """Canonical kind vocabulary for a board thread."""

    POST = "post"
    TICKET = "ticket"
    CONCERN = "concern"
    DM = "dm"


class BoardThreadStatus(StrEnum):
    """Canonical status vocabulary for a board thread."""

    NEW = "new"
    TRIAGED = "triaged"
    DRAFTED = "drafted"
    APPROVED = "approved"
    REPLIED = "replied"
    CLOSED = "closed"


TERMINAL_THREAD_STATUSES: frozenset[str] = frozenset({BoardThreadStatus.REPLIED, BoardThreadStatus.CLOSED})


class BoardThreadRow(Base):
    __tablename__ = "board_threads"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    client_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(16), default=BoardThreadKind.POST)
    status: Mapped[str] = mapped_column(String(16), default=BoardThreadStatus.NEW, index=True)
    subject: Mapped[str] = mapped_column(String(255), default="")
    created_by_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, onupdate=_utc_now)


class BoardMessageRow(Base):
    __tablename__ = "board_messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    thread_id: Mapped[str] = mapped_column(String(64), index=True)
    author_kind: Mapped[str] = mapped_column(String(16), default="client")
    author_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    body: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
