"""Owner-scoped repository for ``pending_actions``.

Generic reads filter the storage user; Composio reads require the authenticated
actor and active organization, so a foreign row is indistinguishable from a
missing one (routers map ``None`` to 404). Separate Composio-only methods grant
active organization owners/admins list/read/reject oversight. Separate approval
methods admit the active staff proposer or an actual same-org owner.
Every state change is a
compare-and-set ``UPDATE ... WHERE status = <expected>``: returns ``None``
when the row is missing, foreign, or no longer in the expected state.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, exists, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.approvals.workflow import STATUSES, InvalidPayloadError, notify_created, validate_payload
from deerflow.persistence.approvals.model import PendingActionRow
from deerflow.persistence.clients.model import ClientAssignmentRow
from deerflow.persistence.organizations.identity import private_organization_id
from deerflow.persistence.organizations.model import OrganizationMemberRow, OrganizationRow
from deerflow.persistence.organizations.resolution import active_organization_for_user, storage_user_id_for_organization
from deerflow.persistence.user.model import UserRow
from deerflow.runtime.user_context import AUTO, _AutoSentinel, get_current_user, get_storage_context, resolve_organization_id, resolve_user_id
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
        # Composio connections belong to the actor, even in shared storage.
        actor = get_current_user()
        organization_id = resolve_organization_id()
        stmt = stmt.where(
            or_(
                and_(PendingActionRow.action_type != "composio_tool_call", PendingActionRow.user_id == user_id),
                and_(PendingActionRow.action_type == "composio_tool_call", PendingActionRow.user_id == (str(actor.id) if actor else ""), PendingActionRow.organization_id == (organization_id or "")),
            )
        )
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
        organization_id: str | None = None,
        action_id: str | None = None,
    ) -> dict:
        uid = resolve_user_id(user_id, method_name="PendingActionRepository.create")
        validate_payload(action_type, target, payload)
        selected_org = organization_id if organization_id is not None else private_organization_id(uid)
        if action_type == "composio_tool_call":
            actor = get_current_user()
            if actor is None or str(actor.id) != uid or not resolve_organization_id() or selected_org != resolve_organization_id():
                raise InvalidPayloadError("Composio proposals require the authenticated actor and active organization")
        row = PendingActionRow(
            id=action_id or uuid.uuid4().hex,
            user_id=uid,
            organization_id=selected_org,
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
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                if action_id is None:
                    raise
                existing = await session.get(PendingActionRow, action_id)
                if existing is None or (existing.user_id, existing.organization_id, existing.action_type, existing.target, existing.original_payload, existing.thread_id, existing.run_id) != (
                    uid,
                    selected_org,
                    action_type,
                    target,
                    payload,
                    thread_id,
                    run_id,
                ):
                    raise InvalidPayloadError("Composio proposal identity conflict") from None
                return _to_dict(existing)
            await session.refresh(row)
            created = _to_dict(row)
        await notify_created(created)
        return created

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

    async def _composio_oversight_scope(self, stmt: Any) -> Any | None:
        """Separate oversight scope; approval additionally verifies the proposer."""
        actor = get_current_user()
        context = get_storage_context()
        if actor is None or context is None or str(actor.id) != context.actor_user_id or not context.organization_id:
            return None
        async with self._sf() as session:
            organization = await active_organization_for_user(session, str(actor.id), context.organization_id)
        if organization is None or organization.role not in {"owner", "admin"} or storage_user_id_for_organization(organization, str(actor.id)) != context.storage_user_id:
            return None
        return stmt.where(PendingActionRow.action_type == "composio_tool_call", PendingActionRow.organization_id == organization.id)

    async def get_composio_for_org(self, action_id: str) -> dict | None:
        stmt = await self._composio_oversight_scope(select(PendingActionRow).where(PendingActionRow.id == action_id))
        if stmt is None:
            return None
        async with self._sf() as session:
            row = (await session.execute(stmt)).scalars().first()
            return _to_dict(row) if row is not None else None

    async def _composio_approval_scope(self, stmt: Any) -> Any | None:
        """Own active staff proposal, or an actual active same-org owner."""
        actor, context = get_current_user(), get_storage_context()
        if actor is None or context is None or str(actor.id) != context.actor_user_id or not context.organization_id:
            return None
        async with self._sf() as session:
            user = await session.get(UserRow, str(actor.id))
            organization = await active_organization_for_user(session, str(actor.id), context.organization_id)
        role = getattr(user, "system_role", None)
        if (
            user is None
            or user.disabled_at is not None
            or role not in {"user", "exec", "admin"}
            or organization is None
            or organization.role not in {"owner", "admin", "member"}
            or storage_user_id_for_organization(organization, str(actor.id)) != context.storage_user_id
        ):
            return None
        proposer_active = exists().where(
            OrganizationMemberRow.organization_id == PendingActionRow.organization_id,
            OrganizationMemberRow.user_id == PendingActionRow.user_id,
            OrganizationMemberRow.status == "active",
            OrganizationMemberRow.role.in_({"owner", "admin", "member"}),
        )
        proposer_staff = exists().where(
            UserRow.id == PendingActionRow.user_id,
            UserRow.disabled_at.is_(None),
            UserRow.system_role.in_({"user", "exec", "admin"}),
        )
        stmt = stmt.where(PendingActionRow.action_type == "composio_tool_call", PendingActionRow.organization_id == organization.id, proposer_active, proposer_staff)
        bound_client_id = select(OrganizationRow.customer_client_id).where(OrganizationRow.id == organization.id, OrganizationRow.status == "active").scalar_subquery()
        for participant in (str(actor.id), PendingActionRow.user_id):
            stmt = stmt.where(
                ~exists().where(
                    ClientAssignmentRow.user_id == participant,
                    ClientAssignmentRow.role == "client_contact",
                    or_(ClientAssignmentRow.organization_id == organization.id, ClientAssignmentRow.client_id == bound_client_id),
                )
            )
        owner_active = exists().where(
            OrganizationMemberRow.organization_id == organization.id,
            OrganizationMemberRow.user_id == str(actor.id),
            OrganizationMemberRow.status == "active",
            OrganizationMemberRow.role == "owner",
        )
        return stmt.where(or_(PendingActionRow.user_id == str(actor.id), owner_active))

    async def get_composio_for_approval(self, action_id: str) -> dict | None:
        stmt = await self._composio_approval_scope(select(PendingActionRow).where(PendingActionRow.id == action_id))
        if stmt is None:
            return None
        async with self._sf() as session:
            row = (await session.execute(stmt)).scalars().first()
            return _to_dict(row) if row is not None else None

    async def _composio_approval_transition(self, action_id: str, *, expected: str, claim=False, **values) -> dict | None:
        actor = get_current_user()
        if actor is None:
            return None
        stmt = update(PendingActionRow).where(PendingActionRow.id == action_id, PendingActionRow.status == expected)
        if expected == "approved":
            stmt = stmt.where(PendingActionRow.decided_by == str(actor.id))
        if claim:
            stmt = stmt.where(PendingActionRow.execution_result.is_(None))
        stmt = await self._composio_approval_scope(stmt)
        if stmt is None:
            return None
        stmt = stmt.values(updated_at=datetime.now(UTC), **values).returning(PendingActionRow)
        async with self._sf() as session:
            row = (await session.execute(stmt)).scalars().first()
            result = _to_dict(row) if row is not None else None
            await session.commit()
            return result

    async def decide_composio(self, action_id: str, *, approve: bool) -> dict | None:
        actor = get_current_user()
        if actor is None:
            return None
        return await self._composio_approval_transition(action_id, expected="pending", status="approved" if approve else "rejected", decided_by=str(actor.id), decided_at=datetime.now(UTC))

    async def claim_composio_handoff(self, action_id: str) -> dict | None:
        return await self._composio_approval_transition(
            action_id, expected="approved", claim=True, execution_result={"state": "outcome_unknown", "attempted": True}, error="outcome_unknown: reconcile Composio destination; never automatically retry"
        )

    async def record_composio_outcome(self, action_id: str, *, status: str, result: dict, error: str | None = None) -> dict | None:
        values = {"status": status, "execution_result": result, "error": error}
        if status == "executed":
            values["executed_at"] = datetime.now(UTC)
        return await self._composio_approval_transition(action_id, expected="approved", **values)

    async def list_composio_for_org(self, *, status: str | None = None, limit: int = 100) -> list[dict]:
        stmt = await self._composio_oversight_scope(select(PendingActionRow))
        if stmt is None or (status is not None and status not in STATUSES):
            return []
        if status is not None:
            stmt = stmt.where(PendingActionRow.status == status)
        stmt = stmt.order_by(PendingActionRow.created_at.desc()).limit(max(1, min(limit, 200)))
        async with self._sf() as session:
            return [_to_dict(row) for row in (await session.execute(stmt)).scalars()]

    async def reject_composio_for_org(self, action_id: str) -> dict | None:
        stmt = await self._composio_oversight_scope(update(PendingActionRow).where(PendingActionRow.id == action_id, PendingActionRow.status == "pending"))
        if stmt is None:
            return None
        actor = get_current_user()
        stmt = stmt.values(status="rejected", decided_by=str(actor.id), decided_at=datetime.now(UTC), updated_at=datetime.now(UTC)).returning(PendingActionRow)
        async with self._sf() as session:
            row = (await session.execute(stmt)).scalars().first()
            rejected = _to_dict(row) if row is not None else None
            await session.commit()
        return rejected

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
        if current["action_type"] == "composio_tool_call" and (new_target != current["target"] or new_payload != current["payload"]):
            raise InvalidPayloadError("Composio approvals bind an exact immutable call; file a new proposal")
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

    async def claim_composio_execution(self, action_id: str) -> dict | None:
        """Durably fence one attempt before transport; a crash leaves unknown, never retryable."""
        uid = resolve_user_id(AUTO, method_name="PendingActionRepository.claim_composio_execution")
        stmt = self._scope(
            update(PendingActionRow).where(
                PendingActionRow.id == action_id,
                PendingActionRow.action_type == "composio_tool_call",
                PendingActionRow.status == "approved",
                PendingActionRow.execution_result.is_(None),
            ),
            uid,
        ).values(execution_result={"state": "outcome_unknown", "attempted": True}, error="outcome_unknown: reconcile Composio destination; never automatically retry", updated_at=datetime.now(UTC))
        async with self._sf() as session:
            result = await session.execute(stmt)
            await session.commit()
            if result.rowcount != 1:
                return None
        return await self.get(action_id)
