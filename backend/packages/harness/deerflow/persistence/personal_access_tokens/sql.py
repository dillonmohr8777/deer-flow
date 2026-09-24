"""SQLAlchemy-backed personal access token storage.

Each method acquires its own short-lived session. The raw ``dfp_…`` token is
generated and returned by the caller (the app layer) exactly once; this
repository only ever persists the SHA-256 digest passed to :meth:`create`.

``organization_id`` (migration 0037_pat_organization) is stamped at creation
time from the request's active organization, the same
``organization_for_write`` pattern as ``FleetBindingRepository`` (`AGENTS.md`
"Organization isolation (M3)"). :meth:`list_for_user` and :meth:`revoke` add
an ``organization_id == active`` filter beside the existing ``user_id``
filter, only when :func:`resolve_organization_id` is non-null.
:meth:`get_active_by_digest` deliberately does not scope by organization --
it runs during PAT *authentication*, before any request-scoped organization
is resolved; the caller (``AuthMiddleware``) uses the returned row's own
``organization_id`` to resolve the token's organization and fails closed if
the owner is no longer an active member of it.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.organizations.resolution import organization_for_write
from deerflow.persistence.personal_access_tokens.model import PersonalAccessTokenRow
from deerflow.runtime.user_context import AUTO, resolve_organization_id, resolve_user_id
from deerflow.utils.time import coerce_iso

logger = logging.getLogger(__name__)


class PersonalAccessTokenRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], *, last_used_write_interval_seconds: float = 300.0) -> None:
        self._sf = session_factory
        self._last_used_write_interval = last_used_write_interval_seconds
        self._last_used_written_at: dict[str, float] = {}

    @staticmethod
    def _scope(stmt: Any, organization_id: str | None) -> Any:
        if organization_id is not None:
            return stmt.where(PersonalAccessTokenRow.organization_id == organization_id)
        return stmt

    @staticmethod
    def _row_to_dict(row: PersonalAccessTokenRow) -> dict[str, Any]:
        d = row.to_dict()
        for key in ("expires_at", "last_used_at", "created_at", "revoked_at"):
            val = d.get(key)
            if isinstance(val, datetime):
                # SQLite drops tzinfo on read; normalize so output is tz-aware.
                d[key] = coerce_iso(val)
        return d

    async def create(
        self,
        *,
        user_id: str,
        name: str,
        scopes: list[str],
        token_digest: str,
        expires_at: datetime | None = None,
    ) -> dict[str, Any]:
        row = PersonalAccessTokenRow(
            id=str(uuid.uuid4()),
            user_id=user_id,
            name=name,
            token_digest=token_digest,
            scopes=sorted(scopes),
            expires_at=expires_at,
            created_at=datetime.now(UTC),
        )
        row.organization_id = organization_for_write(resolve_organization_id(), None, resolve_user_id(AUTO, method_name="PersonalAccessTokenRepository.create"))
        async with self._sf() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return self._row_to_dict(row)

    async def get_active_by_digest(self, token_digest: str) -> dict[str, Any] | None:
        """Return the non-revoked, non-expired row for *token_digest*.

        Revocation and expiry are evaluated here so a stale durable row can
        never authenticate even though it remains readable for audit history.
        """
        async with self._sf() as session:
            row = (await session.execute(select(PersonalAccessTokenRow).where(PersonalAccessTokenRow.token_digest == token_digest))).scalar_one_or_none()
            if row is None or row.revoked_at is not None:
                return None
            expires_at = row.expires_at
            if expires_at is not None:
                # SQLite drops tzinfo on read; normalize before comparing.
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=UTC)
                if expires_at <= datetime.now(UTC):
                    return None
            return self._row_to_dict(row)

    async def list_for_user(self, user_id: str) -> list[dict[str, Any]]:
        stmt = self._scope(select(PersonalAccessTokenRow).where(PersonalAccessTokenRow.user_id == user_id), resolve_organization_id())
        stmt = stmt.order_by(PersonalAccessTokenRow.created_at.desc())
        async with self._sf() as session:
            rows = (await session.execute(stmt)).scalars()
            return [self._row_to_dict(row) for row in rows]

    async def revoke(self, pat_id: str, user_id: str) -> bool:
        """Revoke one of *user_id*'s tokens; returns False if not owned/absent."""
        stmt = update(PersonalAccessTokenRow).where(
            PersonalAccessTokenRow.id == pat_id,
            PersonalAccessTokenRow.user_id == user_id,
            PersonalAccessTokenRow.revoked_at.is_(None),
        )
        stmt = self._scope(stmt, resolve_organization_id()).values(revoked_at=datetime.now(UTC))
        async with self._sf() as session:
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount != 0

    def _should_write_last_used(self, pat_id: str) -> bool:
        now = time.monotonic()
        last = self._last_used_written_at.get(pat_id)
        if last is not None and (now - last) < self._last_used_write_interval:
            return False
        # Bound the stamp cache: revoked/expired tokens never return here, so
        # their entries are stale by definition once the cache outgrows very
        # active token populations.
        if len(self._last_used_written_at) > 4096:
            self._last_used_written_at.clear()
        self._last_used_written_at[pat_id] = now
        return True

    async def touch_last_used(self, pat_id: str) -> None:
        """Best-effort, throttled usage stamp (at most one write per interval).

        Never raises: a failure to stamp usage must not fail the request. On
        failure the throttle window is rolled back so the next attempt
        retries promptly instead of waiting out the full interval.
        """
        if not self._should_write_last_used(pat_id):
            return
        try:
            async with self._sf() as session:
                await session.execute(update(PersonalAccessTokenRow).where(PersonalAccessTokenRow.id == pat_id).values(last_used_at=datetime.now(UTC)))
                await session.commit()
        except Exception:
            self._last_used_written_at.pop(pat_id, None)
            logger.debug("Failed to stamp last_used_at for PAT %s (non-fatal)", pat_id, exc_info=True)
