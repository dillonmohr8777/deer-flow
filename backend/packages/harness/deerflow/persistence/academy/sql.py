"""SQLAlchemy-backed AI Academy progress repository.

Scoped to the active organization and the given user. The router passes the
caller's own id, so one person can never read or change another's progress.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.academy.model import AcademyProgressRow


class AcademyProgressRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def completed_lessons(self, *, organization_id: str, user_id: str) -> set[str]:
        stmt = select(AcademyProgressRow.lesson_id).where(
            AcademyProgressRow.organization_id == organization_id,
            AcademyProgressRow.user_id == user_id,
        )
        async with self._sf() as session:
            return set((await session.execute(stmt)).scalars())

    async def set_completed(self, *, organization_id: str, user_id: str, lesson_id: str, completed: bool) -> None:
        """Mark or unmark one lesson. Both directions are idempotent."""
        async with self._sf() as session:
            if completed:
                key = {"organization_id": organization_id, "user_id": user_id, "lesson_id": lesson_id}
                if await session.get(AcademyProgressRow, key) is None:
                    session.add(AcademyProgressRow(**key, completed_at=datetime.now(UTC)))
            else:
                await session.execute(
                    delete(AcademyProgressRow).where(
                        AcademyProgressRow.organization_id == organization_id,
                        AcademyProgressRow.user_id == user_id,
                        AcademyProgressRow.lesson_id == lesson_id,
                    )
                )
            await session.commit()
