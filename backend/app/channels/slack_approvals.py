"""Slack DM for the approvals inbox: Approve / Edit / Skip buttons on new pending actions.

Config-gated by ``channels.slack.approvals_dm`` (default off). Reuses the approvals
inbox (``pending_actions``) and its adapters -- there is no second queue. Approve
runs the same adapter path as the web Approve button (email/ad_change/other only
mark the row ``ready_to_send``; nothing is emailed), Skip rejects the row, Edit
just links to the item in the UI. Only Slack users in ``user_ids`` may act.
"""

from __future__ import annotations

import html
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

logger = logging.getLogger(__name__)

ACTION_PREFIX = "momo_approval_"
VERBS = ("approve", "edit", "skip")
SUMMARY_CHARS = 600
DEFAULT_BASE_URL = "http://127.0.0.1:2026"

_SECRET_RE = re.compile(r"(xox[abprs]-[\w-]+|xapp-[\w-]+|sk-[\w-]{8,}|Bearer\s+[\w.~+/=-]{8,}|(?i:(?:api[_-]?key|token|password|secret)\s*[:=]\s*)\S+)")


@dataclass(frozen=True)
class ApprovalsDmConfig:
    enabled: bool = False
    user_ids: frozenset[str] = field(default_factory=frozenset)
    base_url: str = DEFAULT_BASE_URL


def parse_config(raw: Any) -> ApprovalsDmConfig:
    """Off unless ``enabled`` is literally true and at least one user id is listed."""
    if not isinstance(raw, dict) or raw.get("enabled") is not True:
        return ApprovalsDmConfig()
    ids = raw.get("user_ids") or []
    if isinstance(ids, str):
        ids = [ids]
    user_ids = frozenset(str(u) for u in ids if str(u))
    if not user_ids:
        return ApprovalsDmConfig()
    base = str(raw.get("base_url") or DEFAULT_BASE_URL).rstrip("/")
    return ApprovalsDmConfig(enabled=True, user_ids=user_ids, base_url=base)


def is_allowed(cfg: ApprovalsDmConfig, user_id: str | None) -> bool:
    return cfg.enabled and bool(user_id) and user_id in cfg.user_ids


def _esc(text: str) -> str:
    return html.escape(_SECRET_RE.sub("[redacted]", text), quote=False)


def _content(row: dict[str, Any]) -> str:
    payload = row.get("payload") or {}
    parts = [str(payload[k]) for k in ("subject", "body", "text") if isinstance(payload.get(k), str) and payload[k].strip()]
    return "\n\n".join(parts) if parts else json.dumps({k: v for k, v in payload.items() if k != "loop"}, default=str)


def _client(row: dict[str, Any]) -> str:
    loop = (row.get("payload") or {}).get("loop")
    client = loop.get("client") if isinstance(loop, dict) else None
    return str(client or row.get("agent_name") or "unassigned")


def item_url(cfg: ApprovalsDmConfig, action_id: str) -> str:
    return f"{cfg.base_url}/workspace/approvals?id={action_id}"


def build_message(row: dict[str, Any], cfg: ApprovalsDmConfig) -> tuple[str, list[dict[str, Any]]]:
    """Return ``(fallback_text, blocks)`` for one pending row. Content is truncated and secret-scrubbed."""
    content = _content(row).strip()
    snippet = content[:SUMMARY_CHARS] + ("..." if len(content) > SUMMARY_CHARS else "")
    title = str(row.get("title") or "").strip() or "Untitled"
    head = f"*{_esc(_client(row))}* | {_esc(str(row['action_type']))} | {_esc(title[:120])}"
    action_id = str(row["id"])
    buttons = [
        {"type": "button", "action_id": f"{ACTION_PREFIX}approve", "value": action_id, "style": "primary", "text": {"type": "plain_text", "text": "Approve"}},
        {"type": "button", "action_id": f"{ACTION_PREFIX}edit", "value": action_id, "text": {"type": "plain_text", "text": "Edit"}},
        {"type": "button", "action_id": f"{ACTION_PREFIX}skip", "value": action_id, "style": "danger", "text": {"type": "plain_text", "text": "Skip"}},
    ]
    blocks: list[dict[str, Any]] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": head}},
        {"type": "section", "text": {"type": "mrkdwn", "text": _esc(snippet) or "_(empty)_"}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f"<{item_url(cfg, action_id)}|Open in Command Center>"}]},
        {"type": "actions", "block_id": f"momo_approval:{action_id}", "elements": buttons},
    ]
    return f"Approval needed: {_client(row)} / {row['action_type']} / {title[:120]}", blocks


def settled_blocks(blocks: list[dict[str, Any]], status_line: str) -> list[dict[str, Any]]:
    """Replace the buttons with a status line so a decided item can't be clicked again."""
    kept = [b for b in blocks if b.get("type") != "actions"]
    return [*kept, {"type": "context", "elements": [{"type": "mrkdwn", "text": re.sub(r"&lt;@(\w+)&gt;", r"<@\1>", _esc(status_line))}]}]


@dataclass(frozen=True)
class ParsedAction:
    verb: str
    item_id: str
    user_id: str
    channel: str | None
    message_ts: str | None
    blocks: list[dict[str, Any]]


def parse_block_action(payload: dict[str, Any]) -> ParsedAction | None:
    """Pull our first button out of a Socket Mode ``block_actions`` payload; ``None`` if it is not ours."""
    if payload.get("type") != "block_actions":
        return None
    for act in payload.get("actions") or []:
        action_id = str(act.get("action_id") or "")
        verb = action_id.removeprefix(ACTION_PREFIX)
        if action_id.startswith(ACTION_PREFIX) and verb in VERBS and act.get("value"):
            message = payload.get("message") or {}
            return ParsedAction(
                verb=verb,
                item_id=str(act["value"]),
                user_id=str((payload.get("user") or {}).get("id") or ""),
                channel=(payload.get("channel") or {}).get("id") or (payload.get("container") or {}).get("channel_id"),
                message_ts=message.get("ts") or (payload.get("container") or {}).get("message_ts"),
                blocks=list(message.get("blocks") or []),
            )
    return None


class ApprovalStore(Protocol):
    async def get(self, action_id: str) -> dict[str, Any] | None: ...
    async def decide(self, row: dict[str, Any], *, approve: bool, decided_by: str) -> dict[str, Any] | None: ...


@dataclass(frozen=True)
class ActionResult:
    kind: str  # denied | edit | approved | skipped | stale | missing
    text: str


async def route_action(action: ParsedAction, cfg: ApprovalsDmConfig, store: ApprovalStore) -> ActionResult:
    """Apply one button press. Permission is checked first, before the row is even read."""
    if not is_allowed(cfg, action.user_id):
        return ActionResult("denied", "Not allowed: you can't act on approvals.")
    row = await store.get(action.item_id)
    if row is None:
        return ActionResult("missing", "That approval no longer exists.")
    if action.verb == "edit":
        return ActionResult("edit", f"Edit it here: {item_url(cfg, action.item_id)}")
    approve = action.verb == "approve"
    decided = await store.decide(row, approve=approve, decided_by=f"slack:{action.user_id}")
    if decided is None:
        return ActionResult("stale", "Already decided, nothing changed.")
    if approve:
        who = f"Approved by <@{action.user_id}>"
        if decided["status"] == "failed":
            return ActionResult("approved", f"{who}, but the action failed: {decided.get('error') or 'unknown error'}")
        # Only a real adapter effect reaches "executed"; email and the like stay approved + ready_to_send.
        return ActionResult("approved", who if decided["status"] == "executed" else f"{who} (draft kept, nothing sent)")
    return ActionResult("skipped", f"Skipped by <@{action.user_id}>")


class DbApprovalStore:
    """Real store over ``pending_actions``. Rows are looked up by id alone: the Slack allowlist is the gate."""

    def __init__(self, session_factory: Any) -> None:
        from deerflow.persistence.approvals import PendingActionRepository

        self._sf = session_factory
        self._repo = PendingActionRepository(session_factory)

    async def get(self, action_id: str) -> dict[str, Any] | None:
        from sqlalchemy import select

        from deerflow.persistence.approvals.model import PendingActionRow
        from deerflow.persistence.approvals.sql import _to_dict

        async with self._sf() as session:
            row = (await session.execute(select(PendingActionRow).where(PendingActionRow.id == action_id))).scalars().first()
            return _to_dict(row) if row is not None else None

    async def decide(self, row: dict[str, Any], *, approve: bool, decided_by: str) -> dict[str, Any] | None:
        owner = row["user_id"]
        decided = await self._repo.decide(row["id"], approve=approve, decided_by=decided_by, user_id=owner)
        if decided is None or not approve:
            return decided
        # Same path as the web Approve button: adapter runs only for the caller that won pending->approved.
        from app.gateway.approval_adapters import execute_approved

        outcome = await execute_approved(decided)
        settled = await self._repo.record_outcome(row["id"], status=outcome.status, result=outcome.detail, error=outcome.error, user_id=owner)
        logger.info("[Slack approvals] %s %s by %s -> %s", row["id"], "approved", decided_by, outcome.status)
        return settled or decided
