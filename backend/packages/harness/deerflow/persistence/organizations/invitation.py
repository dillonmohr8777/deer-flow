"""Persistence model for single-use shared-workspace invitations.

The token itself is never persisted.  Only its SHA-256 digest is stored so a
database read (or an ORM repr) cannot be used to mint an invitation.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base


def _utc_now() -> datetime:
    return datetime.now(UTC)


class InvitationRow(Base):
    """A pending or consumed invitation to one shared organization."""

    __tablename__ = "workspace_invitations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    organization_id: Mapped[str] = mapped_column(String(64), index=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    role: Mapped[str] = mapped_column(String(32), default="admin")
    created_by: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, onupdate=_utc_now)


# Keep a descriptive alias for callers that prefer the table name.  There is
# one mapped class for the table; the alias does not register a second mapper.
WorkspaceInvitationRow = InvitationRow


__all__ = ["InvitationRow", "WorkspaceInvitationRow"]
