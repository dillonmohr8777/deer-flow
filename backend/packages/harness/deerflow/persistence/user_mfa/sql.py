"""SQLAlchemy-backed two-factor authentication (TOTP) repository."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm.attributes import flag_modified

from deerflow.persistence.user_mfa.model import UserMfaRow
from deerflow.utils.time import coerce_iso


class UserMfaRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @staticmethod
    def _row_to_dict(row: UserMfaRow) -> dict[str, Any]:
        d = row.to_dict()
        for key in ("enabled_at", "created_at", "updated_at"):
            val = d.get(key)
            if isinstance(val, datetime):
                d[key] = coerce_iso(val)
        return d

    async def get(self, user_id: str) -> dict[str, Any] | None:
        async with self._sf() as session:
            row = await session.get(UserMfaRow, user_id)
            return self._row_to_dict(row) if row is not None else None

    async def start_enrollment(self, user_id: str, secret_encrypted: str) -> dict[str, Any]:
        """Create (or overwrite) the pending, unconfirmed enrollment row.

        Restarting enrollment before confirming discards the previous
        secret and any recovery codes -- there is nothing to discard on a
        first attempt, and a previously *enabled* row is never reachable
        here (the router 409s before calling this).
        """
        now = datetime.now(UTC)
        async with self._sf() as session:
            row = await session.get(UserMfaRow, user_id)
            if row is None:
                row = UserMfaRow(user_id=user_id, secret_encrypted=secret_encrypted, enabled_at=None, recovery_codes=[], created_at=now, updated_at=now)
                session.add(row)
            else:
                row.secret_encrypted = secret_encrypted
                row.enabled_at = None
                row.recovery_codes = []
                row.updated_at = now
            await session.commit()
            await session.refresh(row)
            return self._row_to_dict(row)

    async def confirm_enrollment(self, user_id: str, recovery_code_hashes: list[str]) -> dict[str, Any]:
        """Mark enrollment enabled and store the (hashed) recovery codes.

        Raises ``LookupError`` if ``start_enrollment`` was never called (or
        the row was since deleted by a disable) -- the router always calls
        this only after a successful :meth:`get`.
        """
        now = datetime.now(UTC)
        async with self._sf() as session:
            row = await session.get(UserMfaRow, user_id)
            if row is None:
                raise LookupError(f"No pending MFA enrollment for user {user_id}")
            row.enabled_at = now
            row.recovery_codes = [{"hash": h, "used_at": None} for h in recovery_code_hashes]
            row.updated_at = now
            await session.commit()
            await session.refresh(row)
            return self._row_to_dict(row)

    async def disable(self, user_id: str) -> bool:
        """Delete the row entirely. Returns False if MFA was not set up at all."""
        async with self._sf() as session:
            row = await session.get(UserMfaRow, user_id)
            if row is None:
                return False
            await session.delete(row)
            await session.commit()
            return True

    async def mark_recovery_code_used(self, user_id: str, code_hash: str) -> bool:
        """Mark one recovery code consumed. Returns False if it was already
        used, unknown, or MFA isn't enabled for this user -- callers must
        already have matched ``code_hash`` via :func:`recovery_code_matches`
        against an unused entry; this only guards the write against a
        concurrent second use of the same code (``with_for_update`` fences
        two simultaneous logins racing to spend one code on Postgres; SQLite
        already serializes writers at the file level).
        """
        async with self._sf() as session:
            row = await session.get(UserMfaRow, user_id, with_for_update=True)
            if row is None or row.enabled_at is None:
                return False
            found = False
            new_codes: list[dict[str, Any]] = []
            for entry in row.recovery_codes:
                if not found and entry.get("hash") == code_hash and entry.get("used_at") is None:
                    new_codes.append({"hash": entry["hash"], "used_at": coerce_iso(datetime.now(UTC))})
                    found = True
                else:
                    new_codes.append(dict(entry))
            if not found:
                return False
            # A fresh list of fresh dicts (not an in-place mutation of the
            # existing objects) so SQLAlchemy's JSON column change-tracking
            # sees a different value; flag_modified is the explicit backstop.
            row.recovery_codes = new_codes
            flag_modified(row, "recovery_codes")
            row.updated_at = datetime.now(UTC)
            await session.commit()
            return True
