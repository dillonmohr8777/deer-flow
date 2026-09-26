"""SQLAlchemy-backed team board repository.

Organization-scoped exactly like ``BoardRepository``: every read/write is
scoped by ``resolve_organization_id()``, and a foreign or missing channel
comes back as ``None`` so the router answers 404. Who counts as staff is the
router's job; this repository only enforces the organization boundary.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.organizations.resolution import organization_for_write
from deerflow.persistence.team_board.model import DEFAULT_TEAM_CHANNELS, TeamChannelRow, TeamMessageRow
from deerflow.runtime.user_context import AUTO, resolve_organization_id, resolve_user_id
from deerflow.utils.time import coerce_iso


def _to_dict(row: TeamChannelRow | TeamMessageRow) -> dict[str, Any]:
    d = row.to_dict()
    for key in ("created_at", "updated_at"):
        val = d.get(key)
        if isinstance(val, datetime):
            d[key] = coerce_iso(val)
    return d


class TeamBoardRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @staticmethod
    def _write_org(method_name: str) -> str | None:
        return organization_for_write(resolve_organization_id(), None, resolve_user_id(AUTO, method_name=method_name))

    async def list_channels(self) -> list[dict]:
        organization_id = resolve_organization_id()
        stmt = select(TeamChannelRow)
        if organization_id is not None:
            stmt = stmt.where(TeamChannelRow.organization_id == organization_id)
        stmt = stmt.order_by(TeamChannelRow.created_at.asc(), TeamChannelRow.id.asc())
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [_to_dict(r) for r in result.scalars()]

    async def ensure_default_channels(self, created_by_user_id: str | None = None) -> list[dict]:
        """Create any missing default channel for the active organization, then list all.

        Idempotent and race-safe: the ``(organization_id, slug)`` unique
        constraint turns a concurrent duplicate insert into a no-op.
        """
        existing = {c["slug"] for c in await self.list_channels()}
        organization_id = self._write_org("TeamBoardRepository.ensure_default_channels")
        base = datetime.now(UTC)
        for offset, (slug, name, topic) in enumerate(DEFAULT_TEAM_CHANNELS):
            if slug in existing:
                continue
            # Microsecond offsets keep the defaults in their declared order.
            stamp = base + timedelta(microseconds=offset)
            row = TeamChannelRow(
                id=uuid.uuid4().hex,
                organization_id=organization_id,
                slug=slug,
                name=name,
                topic=topic,
                created_by_user_id=created_by_user_id,
                created_at=stamp,
                updated_at=stamp,
            )
            async with self._sf() as session:
                session.add(row)
                try:
                    await session.commit()
                except IntegrityError:
                    await session.rollback()
        return await self.list_channels()

    async def get_channel(self, channel_id: str) -> dict | None:
        organization_id = resolve_organization_id()
        async with self._sf() as session:
            row = await session.get(TeamChannelRow, channel_id)
            if row is None or (organization_id is not None and row.organization_id != organization_id):
                return None
            return _to_dict(row)

    async def create_channel(self, *, slug: str, name: str, topic: str = "", created_by_user_id: str | None = None) -> dict | None:
        """Create a channel; ``None`` when the slug is already taken in this organization."""
        now = datetime.now(UTC)
        row = TeamChannelRow(
            id=uuid.uuid4().hex,
            organization_id=self._write_org("TeamBoardRepository.create_channel"),
            slug=slug,
            name=name,
            topic=topic,
            created_by_user_id=created_by_user_id,
            created_at=now,
            updated_at=now,
        )
        async with self._sf() as session:
            session.add(row)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                return None
            await session.refresh(row)
            return _to_dict(row)

    async def list_messages(self, channel_id: str, *, limit: int = 200) -> list[dict] | None:
        """The newest *limit* messages, oldest first; ``None`` for a missing/foreign channel."""
        if await self.get_channel(channel_id) is None:
            return None
        stmt = select(TeamMessageRow).where(TeamMessageRow.channel_id == channel_id).order_by(TeamMessageRow.created_at.desc(), TeamMessageRow.id.desc()).limit(limit)
        async with self._sf() as session:
            result = await session.execute(stmt)
            rows = [_to_dict(r) for r in result.scalars()]
        rows.reverse()
        return rows

    async def add_message(self, channel_id: str, *, author_user_id: str, body: str) -> dict | None:
        """Append one message; ``None`` for a missing/foreign channel."""
        if await self.get_channel(channel_id) is None:
            return None
        row = TeamMessageRow(
            id=uuid.uuid4().hex,
            channel_id=channel_id,
            author_user_id=author_user_id,
            body=body,
            created_at=datetime.now(UTC),
        )
        async with self._sf() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return _to_dict(row)
