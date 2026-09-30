"""SQLAlchemy-backed CEO Desk digest repository (queue item e14).

``ceo_desk_digests`` is organization-scoped exactly like
``board_threads``/``agent_seats``: every read/write is scoped by
``resolve_organization_id()`` via ``organization_for_write``/``_scope``, the
same pattern ``BoardRepository``/``AgentSeatRepository`` use.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.ceo_desk.model import CeoDeskDigestRow
from deerflow.persistence.organizations.resolution import organization_for_write
from deerflow.runtime.user_context import AUTO, resolve_organization_id, resolve_user_id
from deerflow.utils.time import coerce_iso


def _to_dict(row: CeoDeskDigestRow) -> dict[str, Any]:
    d = row.to_dict()
    val = d.get("created_at")
    if isinstance(val, datetime):
        d["created_at"] = coerce_iso(val)
    return d


class CeoDeskDigestRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @staticmethod
    def _scope(stmt: Any, organization_id: str | None) -> Any:
        if organization_id is not None:
            return stmt.where(CeoDeskDigestRow.organization_id == organization_id)
        return stmt

    async def record_digest(
        self,
        *,
        digest_text: str,
        shipped_count: int,
        stuck_count: int,
        needs_my_yes_drafts: int,
        needs_my_yes_ratifications: int,
    ) -> dict:
        organization_id = organization_for_write(resolve_organization_id(), None, resolve_user_id(AUTO, method_name="CeoDeskDigestRepository.record_digest"))
        row = CeoDeskDigestRow(
            id=uuid.uuid4().hex,
            organization_id=organization_id,
            digest_text=digest_text,
            shipped_count=shipped_count,
            stuck_count=stuck_count,
            needs_my_yes_drafts=needs_my_yes_drafts,
            needs_my_yes_ratifications=needs_my_yes_ratifications,
        )
        async with self._sf() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return _to_dict(row)

    async def latest_digest(self, *, organization_id: str | None = None) -> dict | None:
        """Most recent digest for the caller's organization, or *organization_id* explicitly.

        An explicit *organization_id* is for the background sweep (its own
        per-organization storage context already covers ambient resolution,
        but the sweep checks every organization's queue up front, before
        switching context into any one of them).
        """
        scope_id = organization_id if organization_id is not None else resolve_organization_id()
        stmt = self._scope(select(CeoDeskDigestRow), scope_id).order_by(CeoDeskDigestRow.created_at.desc()).limit(1)
        async with self._sf() as session:
            row = (await session.execute(stmt)).scalars().first()
            return _to_dict(row) if row is not None else None
