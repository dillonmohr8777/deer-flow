"""SQLAlchemy-backed Momo Board repository (Workspace Phase 4 item b2).

``board_threads`` is organization-scoped exactly like ``clients``
(``ClientRepository`` in ``clients/sql.py`` is the pattern this mirrors): every
read/write is scoped by ``resolve_organization_id()``, and a foreign or
missing thread is indistinguishable -- callers map both to ``None`` and
routers answer 404. Per-client access (a client member sees only their own
client's threads, an org owner/admin sees all) is enforced by the router,
not here; this repository only enforces the organization boundary.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.board.model import BoardMessageRow, BoardThreadRow, BoardThreadStatus
from deerflow.persistence.organizations.resolution import organization_for_write
from deerflow.runtime.user_context import AUTO, resolve_organization_id, resolve_user_id
from deerflow.utils.time import coerce_iso


def _thread_to_dict(row: BoardThreadRow) -> dict[str, Any]:
    d = row.to_dict()
    for key in ("created_at", "updated_at"):
        val = d.get(key)
        if isinstance(val, datetime):
            d[key] = coerce_iso(val)
    return d


def _message_to_dict(row: BoardMessageRow) -> dict[str, Any]:
    d = row.to_dict()
    val = d.get("created_at")
    if isinstance(val, datetime):
        d["created_at"] = coerce_iso(val)
    return d


class BoardRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @staticmethod
    def _scope(stmt: Any, organization_id: str | None) -> Any:
        if organization_id is not None:
            return stmt.where(BoardThreadRow.organization_id == organization_id)
        return stmt

    async def create_thread(
        self,
        *,
        client_id: str,
        kind: str,
        subject: str = "",
        created_by_user_id: str | None = None,
    ) -> dict:
        now = datetime.now(UTC)
        row = BoardThreadRow(
            id=uuid.uuid4().hex,
            client_id=client_id,
            kind=kind,
            status=BoardThreadStatus.NEW,
            subject=subject,
            created_by_user_id=created_by_user_id,
            created_at=now,
            updated_at=now,
        )
        row.organization_id = organization_for_write(resolve_organization_id(), None, resolve_user_id(AUTO, method_name="BoardRepository.create_thread"))
        async with self._sf() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return _thread_to_dict(row)

    async def get_thread(self, thread_id: str) -> dict | None:
        organization_id = resolve_organization_id()
        async with self._sf() as session:
            row = await session.get(BoardThreadRow, thread_id)
            if row is None or (organization_id is not None and row.organization_id != organization_id):
                return None
            return _thread_to_dict(row)

    async def list_threads(
        self,
        *,
        client_id: str | None = None,
        client_ids: list[str] | None = None,
        status: str | None = None,
    ) -> list[dict]:
        """List threads in the active organization.

        ``client_id`` scopes to one client; ``client_ids`` scopes to a set (an
        empty list yields no rows). Neither means "every client in the
        organization" -- callers that need per-client isolation must supply
        one of them unless the caller is already known to be an org admin.
        """
        organization_id = resolve_organization_id()
        stmt = self._scope(select(BoardThreadRow), organization_id)
        if client_id is not None:
            stmt = stmt.where(BoardThreadRow.client_id == client_id)
        elif client_ids is not None:
            stmt = stmt.where(BoardThreadRow.client_id.in_(client_ids))
        if status is not None:
            stmt = stmt.where(BoardThreadRow.status == status)
        stmt = stmt.order_by(BoardThreadRow.created_at.desc(), BoardThreadRow.id.asc())
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [_thread_to_dict(r) for r in result.scalars()]

    async def patch_thread(self, thread_id: str, *, status: str | None = None, subject: str | None = None) -> dict | None:
        organization_id = resolve_organization_id()
        async with self._sf() as session:
            row = await session.get(BoardThreadRow, thread_id)
            if row is None or (organization_id is not None and row.organization_id != organization_id):
                return None
            if status is not None:
                row.status = status
            if subject is not None:
                row.subject = subject
            await session.commit()
            await session.refresh(row)
            return _thread_to_dict(row)

    async def list_messages(self, thread_id: str) -> list[dict] | None:
        """Ordered message history for one thread, or ``None`` for a missing/foreign thread."""
        if await self.get_thread(thread_id) is None:
            return None
        stmt = select(BoardMessageRow).where(BoardMessageRow.thread_id == thread_id).order_by(BoardMessageRow.created_at.asc(), BoardMessageRow.id.asc())
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [_message_to_dict(r) for r in result.scalars()]

    async def add_message(self, thread_id: str, *, author_kind: str, body: str, author_user_id: str | None = None) -> dict | None:
        """Append one message; ``None`` for a missing/foreign thread."""
        if await self.get_thread(thread_id) is None:
            return None
        row = BoardMessageRow(
            id=uuid.uuid4().hex,
            thread_id=thread_id,
            author_kind=author_kind,
            author_user_id=author_user_id,
            body=body,
            created_at=datetime.now(UTC),
        )
        async with self._sf() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return _message_to_dict(row)

    async def try_add_momo_draft(self, thread_id: str, *, from_statuses: Iterable[str], body: str) -> dict | None:
        """Atomically add Momo's draft message and move *thread_id* to ``drafted``.

        Used by the board draft concierge (a background job with no single
        human caller serializing its writes against the ``/draft`` route or
        against itself under multiple Gateway workers). The status change is
        a single ``UPDATE ... WHERE status IN (...)``: if the thread's status
        is no longer one of *from_statuses* by the time this statement runs
        (another actor, or another concierge pass, already moved it), the
        statement affects zero rows and this call is a no-op that returns
        ``None`` -- the draft message is added only after that compare-and-set
        succeeds, so a losing race never leaves an orphaned draft message
        behind and never overwrites a status the thread already moved past
        (e.g. resetting ``replied`` back to ``drafted``).
        """
        organization_id = resolve_organization_id()
        stmt = update(BoardThreadRow).where(BoardThreadRow.id == thread_id, BoardThreadRow.status.in_(list(from_statuses)))
        stmt = self._scope(stmt, organization_id)
        stmt = stmt.values(status=BoardThreadStatus.DRAFTED)
        async with self._sf() as session:
            result = await session.execute(stmt)
            if result.rowcount != 1:
                await session.rollback()
                return None
            session.add(
                BoardMessageRow(
                    id=uuid.uuid4().hex,
                    thread_id=thread_id,
                    author_kind="momo",
                    author_user_id=None,
                    body=body,
                    created_at=datetime.now(UTC),
                )
            )
            await session.commit()
            row = await session.get(BoardThreadRow, thread_id)
            return _thread_to_dict(row) if row is not None else None
