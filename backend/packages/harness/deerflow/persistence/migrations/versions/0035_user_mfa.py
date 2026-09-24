"""user_mfa: TOTP two-factor authentication.

Revision ID: 0035_user_mfa
Revises: 0034_clients

One row per user. ``enabled_at`` is NULL while enrollment is pending
(started but not yet confirmed with a valid code); ``secret_encrypted``
is a Fernet ciphertext (app.gateway.auth.mfa_crypto), never a plaintext
TOTP secret. ``recovery_codes`` is a JSON list of hashed, single-use
recovery codes -- the raw codes are shown to the user exactly once at
confirmation time and never persisted.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0035_user_mfa"
down_revision: str | Sequence[str] | None = "0034_clients"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("user_mfa"):
        op.create_table(
            "user_mfa",
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("secret_encrypted", sa.Text(), nullable=False),
            sa.Column("enabled_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("recovery_codes", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("user_id"),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("user_mfa"):
        op.drop_table("user_mfa")
