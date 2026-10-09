"""User-scoped persistence for the private MomoBot Agent Room."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.agent_room.model import AgentRoomMessageRow
from deerflow.persistence.user.model import UserRow
from deerflow.utils.time import coerce_iso


class AgentRoomRepository:
    """Append-only owner messages; every read and write names its owner."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def is_system_admin(self, *, user_id: str) -> bool:
        stmt = select(UserRow.id).where(
            UserRow.id == user_id,
            UserRow.system_role == "admin",
            UserRow.disabled_at.is_(None),
        )
        async with self._sf() as session:
            return (await session.execute(stmt)).scalar_one_or_none() is not None

    @staticmethod
    def _to_dict(row: AgentRoomMessageRow) -> dict[str, Any]:
        value = row.to_dict()
        if isinstance(value.get("created_at"), datetime):
            value["created_at"] = coerce_iso(value["created_at"])
        return value

    async def list_messages(self, *, user_id: str, limit: int = 100) -> list[dict[str, Any]]:
        stmt = select(AgentRoomMessageRow).where(AgentRoomMessageRow.user_id == user_id).order_by(AgentRoomMessageRow.created_at.desc(), AgentRoomMessageRow.id.desc()).limit(limit)
        async with self._sf() as session:
            rows = list((await session.execute(stmt)).scalars())
        rows.reverse()
        return [self._to_dict(row) for row in rows]

    async def add_message(
        self,
        *,
        user_id: str,
        author_kind: str,
        body: str,
        agent_id: str | None = None,
        agent_role: str = "",
        message_type: str = "update",
        run_id: str | None = None,
    ) -> dict[str, Any]:
        row = AgentRoomMessageRow(
            id=uuid.uuid4().hex,
            user_id=user_id,
            author_kind=author_kind,
            agent_id=agent_id,
            agent_role=agent_role,
            message_type=message_type,
            body=body,
            run_id=run_id,
            created_at=datetime.now(UTC),
        )
        async with self._sf() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return self._to_dict(row)
