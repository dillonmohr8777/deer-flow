"""Append-only audit event storage (SOC 2 style controls).

Each method acquires its own short-lived session, matching the other
repositories in this package (``personal_access_tokens``, ``feedback``).
:meth:`AuditEventRepository.record` never raises into the request path: a
failure to write the audit row must not fail (or roll back) the action being
audited, so it is logged and swallowed.
"""

from __future__ import annotations

import base64
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.audit_events.model import AuditEventRow
from deerflow.persistence.audit_events.redact import redact_audit_details
from deerflow.utils.time import coerce_iso

logger = logging.getLogger(__name__)

_USER_AGENT_MAX = 256
_DEFAULT_LIMIT = 50
_MAX_LIMIT = 200


def _encode_cursor(row: AuditEventRow) -> str:
    raw = f"{coerce_iso(row.occurred_at)}|{row.id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    raw = base64.urlsafe_b64decode(cursor.encode()).decode()
    iso, row_id = raw.rsplit("|", 1)
    return datetime.fromisoformat(iso), row_id


class AuditEventRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def record(
        self,
        *,
        action: str,
        outcome: str,
        actor_user_id: str | None = None,
        organization_id: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        ip: str | None = None,
        user_agent: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Append one audit row.

        Never raises: any persistence failure is logged at warning level and
        swallowed so an audit-log outage cannot block the audited action.
        """
        try:
            row = AuditEventRow(
                id=str(uuid.uuid4()),
                occurred_at=datetime.now(UTC),
                actor_user_id=actor_user_id,
                organization_id=organization_id,
                action=action,
                target_type=target_type,
                target_id=target_id,
                outcome=outcome,
                ip=ip,
                user_agent=user_agent[:_USER_AGENT_MAX] if user_agent else None,
                details=redact_audit_details(details) if details else None,
            )
            async with self._sf() as session:
                session.add(row)
                await session.commit()
        except Exception:
            logger.warning("Failed to record audit event action=%s (non-fatal)", action, exc_info=True)

    @staticmethod
    def _row_to_dict(row: AuditEventRow) -> dict[str, Any]:
        d = row.to_dict()
        d["occurred_at"] = coerce_iso(row.occurred_at)
        return d

    async def list(
        self,
        *,
        organization_id: str | None,
        action_prefix: str | None = None,
        actor_user_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = _DEFAULT_LIMIT,
        cursor: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Return ``(rows, next_cursor)``, newest first.

        ``organization_id=None`` lists every row regardless of organization
        (for a system admin's cross-tenant audit view); callers that must
        stay tenant scoped always pass their resolved organization id.
        ``cursor`` is the opaque keyset from a previous call's
        ``next_cursor``; ``None`` means "no more rows".
        """
        bounded_limit = max(1, min(limit, _MAX_LIMIT))
        stmt = select(AuditEventRow).order_by(AuditEventRow.occurred_at.desc(), AuditEventRow.id.desc()).limit(bounded_limit + 1)
        if organization_id is not None:
            stmt = stmt.where(AuditEventRow.organization_id == organization_id)
        if action_prefix:
            stmt = stmt.where(AuditEventRow.action.like(f"{action_prefix}%"))
        if actor_user_id:
            stmt = stmt.where(AuditEventRow.actor_user_id == actor_user_id)
        if since is not None:
            stmt = stmt.where(AuditEventRow.occurred_at >= since)
        if until is not None:
            stmt = stmt.where(AuditEventRow.occurred_at <= until)
        if cursor:
            cursor_occurred_at, cursor_id = _decode_cursor(cursor)
            stmt = stmt.where(
                sa.or_(
                    AuditEventRow.occurred_at < cursor_occurred_at,
                    sa.and_(AuditEventRow.occurred_at == cursor_occurred_at, AuditEventRow.id < cursor_id),
                )
            )

        async with self._sf() as session:
            rows = list((await session.execute(stmt)).scalars())

        has_more = len(rows) > bounded_limit
        page = rows[:bounded_limit]
        next_cursor = _encode_cursor(page[-1]) if has_more and page else None
        return [self._row_to_dict(row) for row in page], next_cursor
