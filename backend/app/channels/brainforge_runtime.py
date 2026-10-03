"""Opt-in deterministic Slack workflow within the existing MomoBot channel.

The SQLite ledger records transport IDs only. Canonical work remains read-only.
No model dispatcher is reached; unknown requests are ignored in this pilot.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
import uuid
from typing import Any

from app.channels.brainforge_intake import AdmittedEvent, IntakeLedger, ScopePolicy, admit_event, hydrate_thread
from app.channels.brainforge_workflow import BrainForgeBriefWorkflow


def _response(raw: Any) -> dict:
    data = getattr(raw, "data", raw)
    return dict(data) if hasattr(data, "items") else {}


def _payload_hash(event: AdmittedEvent) -> str:
    return hashlib.sha256(json.dumps(vars(event), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class BrainForgeRuntime:
    def __init__(self, channel: Any, config: dict[str, Any]) -> None:
        self.channel = channel
        self.config = config
        self.policy = ScopePolicy(config["team_id"], frozenset(config["allowed_users"]), config["channel_clients"], config["bot_user_id"])
        if not self.policy.valid:
            raise ValueError("exact nonempty Slack scope required")
        self.owner = config.get("owner_user_id")
        if "__owner__" in self.policy.channel_clients.values() and self.owner not in self.policy.allowed_users:
            raise ValueError("aggregate owner route requires an explicit allowed Slack owner")
        self.require_connection = config.get("require_connection", True) is not False
        if self.require_connection and (channel._connection_repo is None or not config.get("connection_owner_id")):
            raise ValueError("persisted tenant binding and expected connection owner required")
        self.workflow = BrainForgeBriefWorkflow(config["workflow"])
        self.ledger = IntakeLedger(config["ledger_path"])
        self._slots = asyncio.Semaphore(1)

    async def validate_transport(self) -> None:
        auth = _response(await asyncio.to_thread(self.channel._web_client.auth_test))
        if auth.get("ok") is not True or auth.get("team_id") != self.policy.team_id or auth.get("user_id") != self.policy.bot_user_id:
            raise ValueError("Slack runtime identity doesn't match reviewed scope")

    def _admit(self, event: dict, team_id: str | None) -> AdmittedEvent | None:
        followed = False
        try:
            if event.get("thread_ts"):
                followed = self.ledger.followed(str(team_id or ""), str(event.get("channel") or ""), event["thread_ts"])
        except ValueError:
            return None
        admitted = admit_event(self.policy, event, team_id=team_id, followed_thread=followed)
        if admitted is None or (admitted.client_id == "__owner__" and admitted.user_id != self.owner):
            return None
        text = re.sub(r"^<@!?" + re.escape(self.policy.bot_user_id) + r"(?:\|[^>\n]+)?>\s*", "", admitted.text).strip().casefold()
        return admitted if text in {"brief", "forge brief", "/forge brief"} else None

    def prepare(self, event: dict, *, team_id: str | None) -> AdmittedEvent | None:
        """SDK thread: persist admitted identity before the transport ACK."""
        admitted = self._admit(event, team_id)
        if admitted is None:
            return None
        inserted = self.ledger.enqueue(
            admitted.team_id, admitted.channel_id, admitted.message_ts,
            client_id=admitted.client_id, thread_ts=admitted.thread_ts,
            payload_sha256=_payload_hash(admitted), user_id=admitted.user_id,
        )
        return admitted if inserted else None

    async def _bound_client(self, event: AdmittedEvent):
        if not self.require_connection:
            return self.channel._web_client
        inbound = self.channel._make_inbound(chat_id=event.channel_id, user_id=event.user_id, text="", thread_ts=event.thread_ts, metadata={"team_id": event.team_id})
        inbound = await self.channel._attach_connection_identity(inbound, team_id=event.team_id)
        if not inbound.connection_id or inbound.workspace_id != event.team_id or inbound.owner_user_id != self.config["connection_owner_id"]:
            raise ValueError("sender has no matching persisted tenant binding")
        credentials = await self.channel._connection_repo.get_credentials(inbound.connection_id, owner_user_id=inbound.owner_user_id)
        token = credentials.get("access_token") if credentials else None
        if not token:
            raise ValueError("bound Slack credentials unavailable; no operator fallback")
        client = self.channel._web_client_factory(token=token, retry_handlers=[])
        auth = _response(await asyncio.to_thread(client.auth_test))
        if auth.get("ok") is not True or auth.get("team_id") != event.team_id:
            raise ValueError("bound credentials belong to a different workspace")
        return client

    async def _thread(self, client: Any, *, channel: str, root: str, event: str):
        async def fetch_page(**kwargs):
            return _response(await asyncio.to_thread(client.conversations_replies, **kwargs))
        return await hydrate_thread(fetch_page, team_id=self.policy.team_id, channel_id=channel, thread_ts=root, event_ts=event)

    async def run(self, event: AdmittedEvent) -> None:
        async with self._slots:
            claim = await asyncio.to_thread(self.ledger.claim, event.team_id, event.channel_id, event.message_ts, lease_seconds=300)
            if claim is None:
                return
            try:
                client = await self._bound_client(event)
                context = await self._thread(client, channel=event.channel_id, root=event.thread_ts, event=event.message_ts)
                if not context.complete:
                    raise ValueError("full scoped Slack thread could not be verified")
                actual = next(row for row in context.messages if row["ts"] == event.message_ts)
                if actual["user"] != event.user_id or actual["text"].strip() != event.text:
                    raise ValueError("trigger identity changed on provider readback")
                result = await asyncio.to_thread(self.workflow.run, job_key=f"{event.team_id}:{event.channel_id}:{event.message_ts}", client_id=event.client_id, thread_sha256=context.sha256)
                # Fence before network IO: crash/timeout after this is held, never blind-replayed.
                if not await asyncio.to_thread(self.ledger.uncertain, claim):
                    return
                # SDK retry middleware can otherwise retry an ambiguous POST.
                client.retry_handlers = []
                response = _response(await asyncio.to_thread(
                    client.chat_postMessage, channel=event.channel_id, thread_ts=event.thread_ts,
                    text=result.text, mrkdwn=False, unfurl_links=False, unfurl_media=False,
                    client_msg_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"brainforge:{event.team_id}:{event.channel_id}:{event.message_ts}")),
                ))
                if response.get("ok") is True and response.get("ts"):
                    await asyncio.to_thread(self.ledger.delivered, claim, response["ts"])
            except asyncio.CancelledError:
                # Any send already attempted is durably uncertain; no retry on shutdown.
                raise
            except Exception:
                # Only claimed (definitely unsent) work can transition to failed.
                await asyncio.to_thread(self.ledger.failed, claim)
                # Provider exceptions may contain response bodies; never log them here.

    async def recover(self) -> int:
        """Bounded restart readback: only queued or expired claims may resume."""
        rows = await asyncio.to_thread(self.ledger.pending, 100, eligible_only=True)
        processed = 0
        for row in rows:
            if row["state"] not in {"queued", "claimed"} or (row["state"] == "claimed" and (row["lease_until"] or 0) > time.time()):
                continue
            user = row.get("user_id")
            if row["team_id"] != self.policy.team_id or row["channel_id"] not in self.policy.channel_clients or user not in self.policy.allowed_users:
                continue
            route = self.policy.channel_clients[row["channel_id"]]
            if route != row["client_id"] or (route == "__owner__" and user != self.owner):
                continue
            identity = AdmittedEvent(row["team_id"], row["channel_id"], user, route, row["message_ts"], row["thread_ts"], "")
            try:
                client = await self._bound_client(identity)
                context = await self._thread(client, channel=identity.channel_id, root=identity.thread_ts, event=identity.message_ts)
                if not context.complete:
                    continue
                original = next(message for message in context.messages if message["ts"] == identity.message_ts)
                event = {"type": "message", "channel": identity.channel_id, "user": original["user"], "ts": identity.message_ts, "thread_ts": identity.thread_ts, "text": original["text"], "channel_type": "im" if identity.channel_id.startswith("D") else "channel"}
                admitted = self._admit(event, identity.team_id)
                if admitted and _payload_hash(admitted) == row["payload_sha256"]:
                    await self.run(admitted)
                    processed += 1
            except Exception:
                # Missing access/changed identity is a held receipt, not a retry loop.
                continue
        return processed

    async def close(self) -> None:
        await asyncio.to_thread(self.ledger.close)
