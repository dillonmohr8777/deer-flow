"""Slack side of the MomoBot desktop handoff: ``desktop``, ``approve``, ``reject`` and result posts.

Who may do what comes from the bound Slack user id and the ``roster`` config,
never from message text. Jobs go through the existing fleet-work routes (the
channel manager calls them as the bound owner), so the router's own roster and
org-admin checks still apply on top of the gate here.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from app.channels.message_bus import OutboundMessage
from deerflow.config.roster_config import RosterConfig, client_allowed, scope_for

logger = logging.getLogger(__name__)

# (method, path, json body) -> (http status, json body)
Api = Callable[[str, str, dict[str, Any] | None], Awaitable[tuple[int, dict[str, Any]]]]

_DESKTOP_START = re.compile(r"^(desktop(\s|$)|(approve|reject)\s+[0-9a-f]{6,40}\s*$)", re.IGNORECASE)
_DM_CLIENT = re.compile(r"^([a-z0-9][a-z0-9-]{0,95})\s*:\s*(.+)$", re.DOTALL)
_SHORT_ID = re.compile(r"^(?:fleet-batch-)?([0-9a-f]{6,31})")
MAX_TASK_CHARS = 4000
RESULT_CHARS = 1500
_FAIL = "Couldn't reach the job queue; nothing was changed."


def as_command(text: str) -> str:
    """``desktop ...`` / ``approve <id>`` / ``reject <id>`` (after the @mention) become ``/momobot ...``."""
    stripped = text.strip()
    return f"/momobot {stripped}" if _DESKTOP_START.match(stripped) else text


def short_id(batch_id: str) -> str:
    return batch_id.removeprefix("fleet-batch-")[:8]


def _approvers(roster: RosterConfig) -> str:
    admins = sorted(uid for uid, user in roster.users.items() if user.role == "admin")
    return " ".join(f"<@{uid}>" for uid in admins)


async def handle(
    *,
    sub: str,
    rest: str,
    user_id: str,
    chat_id: str,
    message_id: str,
    team_id: str | None,
    connection_id: str | None,
    roster: RosterConfig,
    api: Api,
    thread_id: Callable[[], Awaitable[str]],
) -> str:
    scope = scope_for(roster, user_id)  # identity only; the text never reaches this
    if scope["role"] is None:
        return "You're not on the MomoBot roster, so I can't run desktop jobs for you."
    if sub == "desktop":
        return await _submit(rest.strip(), scope, user_id, chat_id, message_id, team_id, connection_id, roster, api, thread_id)
    if scope["role"] != "admin":
        return f"Only a MomoBot admin can {sub} desktop jobs."
    match = _SHORT_ID.match(rest.strip().lower())
    if not match:
        return f"Usage: {sub} <job id>"
    job = match.group(1)
    status, body = await api("POST", f"/api/fleet/work/batches/{job}/{sub}", None)
    if status == 200:
        client = (body.get("execution_spec") or {}).get("client_id", "the client")
        return f"Approved desktop job {job[:8]} for {client}. The Mac will pick it up shortly." if sub == "approve" else f"Rejected desktop job {job[:8]} for {client}. Nothing ran."
    if status == 404:
        return f"No desktop job {job[:8]} found."
    if status == 409:
        return f"Desktop job {job[:8]} was already approved, so I left it alone."
    if status == 403:
        return f"Your MomoBot account isn't an org admin, so I can't {sub} that job."
    return _FAIL


async def _submit(task, scope, user_id, chat_id, message_id, team_id, connection_id, roster, api, thread_id) -> str:
    client = roster.channel_clients.get(chat_id)
    if client is None:
        if not chat_id.startswith("D"):
            return "This channel isn't linked to a client yet. Ask in the client's channel, or DM me: desktop <client-id>: <task>"
        match = _DM_CLIENT.match(task)
        if not match:
            return "In a DM, write: desktop <client-id>: <task>"
        client, task = match.group(1), match.group(2).strip()
    if not task:
        return "What should the desktop do? Write: desktop <task>"
    if len(task) > MAX_TASK_CHARS:
        return f"That task is too long ({len(task)} characters, max {MAX_TASK_CHARS})."
    if not client_allowed(scope, client):
        return f"You're not on the roster for {client}, so I can't queue desktop jobs for it."
    origin = {"channel": chat_id, **({"team": team_id} if team_id else {}), **({"connection": connection_id} if connection_id else {})}
    status, body = await api(
        "POST",
        "/api/fleet/work/batches",
        {
            "thread_id": await thread_id(),
            "title": f"Slack desktop job for {client}",
            "lane": "desktop",
            "data_class": "private",
            "items": [{"key": "task", "prompt": task}],
            "submission_key": hashlib.sha256(f"slack:{chat_id}:{message_id}".encode()).hexdigest()[:64],
            "client_id": client,
            "requester": user_id,
            "slack_origin": origin,
        },
    )
    if status == 403:
        return f"The job queue refused that request for {client}."
    if status not in (200, 201) or "id" not in body:
        return _FAIL
    job = short_id(body["id"])
    return f"Queued desktop job {job} for {client}. Waiting for approval from Dillon or Sean ({_approvers(roster) or 'a MomoBot admin'}): reply `@MomoBot approve {job}` or `@MomoBot reject {job}`."


def result_text(row: dict[str, Any]) -> str:
    spec = row["spec"]
    head = f"<@{spec['requester']}> desktop job {short_id(row['id'])} for {spec['client_id']}"
    if row["status"] == "completed" and row.get("result"):
        return f"{head} finished:\n{row['result'][:RESULT_CHARS]}"
    return f"{head} failed: {(row.get('error') or 'no result came back')[:300]}"


async def post_finished(repo: Any, publish: Callable[[OutboundMessage], Awaitable[None]], *, now: datetime | None = None) -> int:
    """Announce each finished Slack-origin desktop job once, top-level in its channel."""
    now = now or datetime.now(UTC)
    sent = 0
    for row in await repo.desktop_results_to_notify(since=now - timedelta(hours=24)):
        origin = row["spec"]["slack_origin"]
        connection = origin.get("connection")
        await publish(
            OutboundMessage(
                channel_name="slack",
                chat_id=origin["channel"],
                thread_id="",
                text=result_text(row),
                connection_id=connection,
                owner_user_id=row["user_id"] if connection else None,
                metadata={"team_id": origin.get("team")},
            )
        )
        await repo.mark_desktop_notified(row["id"], now=now)
        sent += 1
    return sent


async def notify_loop(get_repo: Callable[[], Any], publish: Callable[[OutboundMessage], Awaitable[None]], interval: float = 30.0) -> None:
    while True:
        try:
            repo = get_repo()
            if repo is not None:
                await post_finished(repo, publish)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("[desktop] posting finished desktop jobs failed")
        await asyncio.sleep(interval)
