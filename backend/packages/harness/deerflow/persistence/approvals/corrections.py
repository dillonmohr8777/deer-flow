"""Per-client corrections ledger: what a reviewer changed before approving an agent's proposal.

Client identity: an approval only carries ``agent_name``. A fleet-stamped agent is
bound to a client (``fleet_agent_bindings``), so the key is ``client:<client_id>``
and every agent of that client shares one ledger. An agent with no binding falls
back to ``agent:<name>`` (the narrowest scope that exists); no agent, no record.
"""

from __future__ import annotations

import difflib
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.approvals.model import ClientCorrectionRow
from deerflow.persistence.fleet.model import FleetAgentBindingRow
from deerflow.persistence.organizations.identity import private_organization_id

_CLIP = 600


def summarize_edit(original: dict, edited: dict) -> str:
    """Short, human-readable diff: per changed field, words added and removed."""
    parts = []
    for key in sorted(set(original) | set(edited)):
        a, b = original.get(key), edited.get(key)
        if a == b:
            continue
        if isinstance(a, str) and isinstance(b, str):
            ops = difflib.SequenceMatcher(None, a.split(), b.split()).get_opcodes()
            added = sum(j2 - j1 for t, _, _, j1, j2 in ops if t in ("replace", "insert"))
            removed = sum(i2 - i1 for t, i1, i2, _, _ in ops if t in ("replace", "delete"))
            parts.append(f"{key}: +{added}/-{removed} words")
        else:
            parts.append(f"{key}: changed")
    return "; ".join(parts) or "no field changes"


def _clip(payload: dict) -> dict:
    return {k: (v[:_CLIP] if isinstance(v, str) else v) for k, v in payload.items()}


class ClientCorrectionRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def client_key_for(self, user_id: str, agent_name: str | None) -> str | None:
        if not agent_name:
            return None
        stmt = select(FleetAgentBindingRow.client_id).where(FleetAgentBindingRow.agent_name == agent_name, FleetAgentBindingRow.agent_owner_user_id == user_id).order_by(FleetAgentBindingRow.created_at).limit(1)
        async with self._sf() as session:
            client_id = (await session.execute(stmt)).scalars().first()
        return f"client:{client_id}" if client_id else f"agent:{agent_name}"

    async def record_for_approval(self, approval: dict, *, approver: str) -> dict | None:
        """Record an approved-with-edits action. ``None`` when nothing was edited or the client is unknown."""
        original, edited = approval["original_payload"], approval["payload"]
        if original == edited:
            return None
        key = await self.client_key_for(approval["user_id"], approval.get("agent_name"))
        if key is None:
            return None
        row = ClientCorrectionRow(
            id=uuid.uuid4().hex,
            user_id=approval["user_id"],
            organization_id=private_organization_id(approval["user_id"]),
            client_key=key,
            action_type=approval["action_type"],
            approval_id=approval["id"],
            original=original,
            edited=edited,
            summary=summarize_edit(original, edited),
            approver=approver,
        )
        async with self._sf() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row.to_dict()

    async def recent(self, user_id: str, client_key: str, limit: int = 10) -> list[dict[str, Any]]:
        stmt = select(ClientCorrectionRow).where(ClientCorrectionRow.user_id == user_id, ClientCorrectionRow.client_key == client_key).order_by(ClientCorrectionRow.created_at.desc()).limit(limit)
        async with self._sf() as session:
            return [r.to_dict() for r in (await session.execute(stmt)).scalars()]


def render_corrections(rows: list[dict]) -> str:
    """Prompt block, oldest first so the newest correction is the last thing read."""
    if not rows:
        return ""
    lines = ["<client_corrections>", "A reviewer edited earlier drafts for this client before approving them. Match the edited style and facts, not the originals."]
    for r in reversed(rows):
        lines.append(f"- {r['action_type']} ({r['summary']}). Draft: {_clip(r['original'])} Approved: {_clip(r['edited'])}")
    lines.append("</client_corrections>")
    return "\n".join(lines)
