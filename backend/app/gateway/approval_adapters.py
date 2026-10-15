"""Execution adapters for approved actions. Nothing here runs before approval.

``execute_approved`` is the single door: the router calls it only for the
caller that won the pending->approved compare-and-set. Email and ad changes are
deliberate stubs (no live writes) that leave the row ``approved`` with
``detail.state == "ready_to_send"`` until a real integration is wired.
"""

from __future__ import annotations

import logging
from typing import Any

from deerflow.approvals import ActionAdapter, AdapterOutcome

logger = logging.getLogger(__name__)


class SlackAdapter:
    """Post as the configured Slack bot via the IM channel service. No "sent using" footer is added."""

    async def execute(self, action: dict[str, Any]) -> AdapterOutcome:
        from app.channels.message_bus import OutboundMessage
        from app.channels.service import get_channel_service

        service = get_channel_service()
        channel = service.get_channel("slack") if service is not None else None
        # SlackChannel.send() returns silently when it has no web client, so check first.
        if channel is None or getattr(channel, "_web_client", None) is None:
            return AdapterOutcome("failed", error="Slack is not configured on this Gateway")
        payload = action["payload"]
        thread_ts = payload.get("thread_ts")
        try:
            await channel.send(
                OutboundMessage(
                    channel_name="slack",
                    chat_id=action["target"],
                    thread_id=action.get("thread_id") or "",
                    text=payload["text"],
                    thread_ts=thread_ts if isinstance(thread_ts, str) and thread_ts else None,
                )
            )
        except Exception as exc:
            logger.exception("Approved Slack action %s failed", action["id"])
            return AdapterOutcome("failed", error=f"Slack send failed: {type(exc).__name__}")
        return AdapterOutcome("executed", {"channel": action["target"]})


class ReadyToSendStub:
    """Marks the action ready; performs no external write."""

    def __init__(self, reason: str) -> None:
        self._reason = reason

    async def execute(self, action: dict[str, Any]) -> AdapterOutcome:
        return AdapterOutcome("approved", {"state": "ready_to_send", "note": self._reason})


ADAPTERS: dict[str, ActionAdapter] = {
    "slack_message": SlackAdapter(),
    "email": ReadyToSendStub("Approved. Gmail sending is not wired yet; send this manually."),
    "ad_change": ReadyToSendStub("Approved. Ad changes are never applied automatically; apply this manually."),
    "other": ReadyToSendStub("Approved. No executor exists for this type; handle it manually."),
}


# Adapters contributed by extensions (see ``deerflow.approvals.register_action_type``). Startup-only.
_EXTENSION_ADAPTERS: dict[str, ActionAdapter] = {}


def register_adapter(action_type: str, adapter: ActionAdapter) -> None:
    _EXTENSION_ADAPTERS[action_type] = adapter


async def execute_approved(action: dict[str, Any]) -> AdapterOutcome:
    adapter = ADAPTERS.get(action["action_type"]) or _EXTENSION_ADAPTERS.get(action["action_type"])
    if adapter is None:
        return AdapterOutcome("failed", error=f"No adapter for {action['action_type']!r}")
    try:
        return await adapter.execute(action)
    except Exception as exc:
        logger.exception("Adapter crashed for approved action %s", action["id"])
        return AdapterOutcome("failed", error=f"Adapter error: {type(exc).__name__}")
