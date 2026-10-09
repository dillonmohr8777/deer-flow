"""ORM model for TOTP-based two-factor authentication (migration 0036_user_mfa)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base


class UserMfaRow(Base):
    """One row per user. Present but ``enabled_at is None`` means enrollment
    was started (secret generated) but never confirmed with a valid code.

    ``recovery_codes`` is a JSON list of ``{"hash": <sha256 hex>, "used_at":
    <iso timestamp | None>}``, populated once at enrollment confirmation and
    never regenerated. The raw codes themselves are never persisted.
    """

    __tablename__ = "user_mfa"

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    # Fernet ciphertext (app.gateway.auth.mfa_crypto) of the base32 TOTP secret.
    secret_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recovery_codes: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
