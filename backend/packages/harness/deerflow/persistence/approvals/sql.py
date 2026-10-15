"""Owner-scoped repository for ``pending_actions``.

Every read filters ``user_id == resolve_user_id(AUTO)`` plus the active
organization when one is set, so a foreign row is indistinguishable from a
missing one (routers map ``None`` to 404). Every state change is a
compare-and-set ``UPDATE ... WHERE status = <expected>``: returns ``None``
when the row is missing, foreign, or no longer in the expected state.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.approvals.workflow import STATUSES, validate_payload
from deerflow.persistence.approvals.model import PendingActionRow
from deerflow.persistence.organizations.identity import private_organization_id
from deerflow.runtime.user_context import AUTO, _AutoSentinel, resolve_organization_id, resolve_user_id
from deerflow.utils.time import coerce_iso

_TIME_KEYS = ("created_at", "updated_at", "decided_at", "executed_at")


def _to_dict(row: PendingActionRow) -> dict[str, Any]:
    d = row.to_dict()
    for key in _TIME_KEYS:
        if isinstance(d.get(key), datetime):
            d[key] = coerce_iso(d[key])
    return d


class PendingActionRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        return self._sf

    @staticmethod
    def _scope(stmt: Any, user_id: str) -> Any:
        stmt = stmt.where(PendingActionRow.user_id == user_id)
        organization_id = resolve_organization_id()
        if organization_id is not None:
            stmt = stmt.where(PendingActionRow.organization_id == organization_id)
        return stmt

    async def create(
        self,
        *,
        action_type: str,
        target: str,
        payload: dict,
        title: str = "",
        thread_id: str | None = None,
        run_id: str | None = None,
        agent_name: str | None = None,
        fact_check: dict | None = None,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> dict:
        uid = resolve_user_id(user_id, method_name="PendingActionRepository.create")
        validate_payload(action_type, target, payload)
        row = PendingActionRow(
            id=uuid.uuid4().hex,
            user_id=uid,
            organization_id=private_organization_id(uid),
            action_type=action_type,
            title=title[:255],
            target=target[:512],
            payload=payload,
            original_payload=payload,
            status="pending",
            thread_id=thread_id,
            run_id=run_id,
            agent_name=agent_name,
            fact_check=fact_check,
        )
        async with self._sf() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return _to_dict(row)

    async def get(self, action_id: str, *, user_id: str | None | _AutoSentinel = AUTO) -> dict | None:
        uid = resolve_user_id(user_id, method_name="PendingActionRepository.get")
        stmt = self._scope(select(PendingActionRow).where(PendingActionRow.id == action_id), uid)
        async with self._sf() as session:
            row = (await session.execute(stmt)).scalars().first()
            return _to_dict(row) if row is not None else None

    async def list(self, *, status: str | None = None, limit: int = 100, user_id: str | None | _AutoSentinel = AUTO) -> list[dict]:
        uid = resolve_user_id(user_id, method_name="PendingActionRepository.list")
        stmt = self._scope(select(PendingActionRow), uid)
        if status is not None:
            if status not in STATUSES:
                return []
            stmt = stmt.where(PendingActionRow.status == status)
        stmt = stmt.order_by(PendingActionRow.created_at.desc()).limit(max(1, min(limit, 200)))
        async with self._sf() as session:
            return [_to_dict(r) for r in (await session.execute(stmt)).scalars()]

    async def _transition(self, action_id: str, uid: str, expected: str, **values: Any) -> dict | None:
        stmt = self._scope(update(PendingActionRow).where(PendingActionRow.id == action_id, PendingActionRow.status == expected), uid)
        stmt = stmt.values(updated_at=datetime.now(UTC), **values)
        async with self._sf() as session:
            result = await session.execute(stmt)
            await session.commit()
            if result.rowcount != 1:
                return None
        return await self.get(action_id, user_id=uid)

    async def edit(self, action_id: str, *, target: str | None = None, payload: dict | None = None, title: str | None = None, user_id: str | None | _AutoSentinel = AUTO) -> dict | None:
        """Edit a still-pending action. Validated against the (possibly new) target."""
        uid = resolve_user_id(user_id, method_name="PendingActionRepository.edit")
        current = await self.get(action_id, user_id=uid)
        if current is None or current["status"] != "pending":
            return None
        new_target = current["target"] if target is None else target
        new_payload = current["payload"] if payload is None else payload
        validate_payload(current["action_type"], new_target, new_payload)
        values: dict[str, Any] = {"target": new_target[:512], "payload": new_payload}
        if title is not None:
            values["title"] = title[:255]
        return await self._transition(action_id, uid, "pending", **values)

    async def set_fact_check(self, action_id: str, fact_check: dict | None, *, user_id: str | None | _AutoSentinel = AUTO) -> dict | None:
        """Replace the stored fact check of a still-pending action (used when an edit changes the claims)."""
        uid = resolve_user_id(user_id, method_name="PendingActionRepository.set_fact_check")
        return await self._transition(action_id, uid, "pending", fact_check=fact_check)

    async def decide(self, action_id: str, *, approve: bool, decided_by: str, user_id: str | None | _AutoSentinel = AUTO) -> dict | None:
        uid = resolve_user_id(user_id, method_name="PendingActionRepository.decide")
        return await self._transition(
            action_id,
            uid,
            "pending",
            status="approved" if approve else "rejected",
            decided_by=decided_by,
            decided_at=datetime.now(UTC),
        )

    async def record_outcome(self, action_id: str, *, status: str, result: dict, error: str | None = None, user_id: str | None | _AutoSentinel = AUTO) -> dict | None:
        """Executor-only: settle an ``approved`` row as executed/failed (or leave it approved with a stub result)."""
        uid = resolve_user_id(user_id, method_name="PendingActionRepository.record_outcome")
        values: dict[str, Any] = {"status": status, "execution_result": result, "error": error}
        if status == "executed":
            values["executed_at"] = datetime.now(UTC)
        return await self._transition(action_id, uid, "approved", **values)
