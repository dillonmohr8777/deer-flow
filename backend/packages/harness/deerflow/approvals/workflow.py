"""Approvals inbox vocabulary: action types, status machine, payload validation, adapter contract.

Status machine (the repository enforces each edge with a compare-and-set
UPDATE, so two reviewers racing can never both win)::

    pending -> approved | rejected
    approved -> executed | failed          (set only by the executor)

Nothing in this package performs a side effect. Adapters live next to the
integration they drive (the Slack adapter is in ``app.gateway``, since it
needs the IM channel service the harness must not import).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

ACTION_TYPES = ("slack_message", "email", "ad_change", "other")
STATUSES = ("pending", "approved", "rejected", "executed", "failed")
MAX_PAYLOAD_BYTES = 20_000

ActionType = Literal["slack_message", "email", "ad_change", "other"]

# Action types contributed by extensions: name -> validator(target, payload). Startup-only.
_EXTENSION_TYPES: dict[str, Callable[[str, dict[str, Any]], None]] = {}


def register_action_type(name: str, validator: Callable[[str, dict[str, Any]], None]) -> None:
    """Let an extension add an approval action type. Raise ``InvalidPayloadError`` from ``validator`` to refuse a payload."""
    if name in ACTION_TYPES or len(name) > 32:
        raise ValueError(f"Cannot register action type {name!r}")
    _EXTENSION_TYPES[name] = validator


# Observers told about every newly filed row (e.g. the Slack approvals DM). Registered by channels at start.
_CREATED_HOOKS: list[Callable[[dict[str, Any]], Any]] = []


def register_created_hook(hook: Callable[[dict[str, Any]], Any]) -> None:
    if hook not in _CREATED_HOOKS:
        _CREATED_HOOKS.append(hook)


def unregister_created_hook(hook: Callable[[dict[str, Any]], Any]) -> None:
    if hook in _CREATED_HOOKS:
        _CREATED_HOOKS.remove(hook)


async def notify_created(row: dict[str, Any]) -> None:
    """Run created-row hooks (sync or async). A hook failure or hang never blocks filing."""
    import asyncio
    import inspect
    import logging

    for hook in list(_CREATED_HOOKS):
        try:
            result = hook(row)
            if inspect.isawaitable(result):
                await asyncio.wait_for(result, timeout=10)
        except Exception:
            logging.getLogger(__name__).warning("approval created-hook failed for %s", row.get("id"), exc_info=True)


class InvalidPayloadError(ValueError):
    """The proposed or edited payload cannot be sent as the given action type."""


def _text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    return value.strip() if isinstance(value, str) else ""


def validate_payload(action_type: str, target: str, payload: Any) -> None:
    """Reject a proposal that could never execute, at propose *and* edit time."""
    if action_type not in ACTION_TYPES and action_type not in _EXTENSION_TYPES:
        raise InvalidPayloadError(f"Unknown action type {action_type!r}")
    if not isinstance(payload, dict):
        raise InvalidPayloadError("Payload must be an object")
    import json

    if len(json.dumps(payload, default=str)) > MAX_PAYLOAD_BYTES:
        raise InvalidPayloadError("Payload is too large")
    if action_type == "slack_message":
        if not target.strip():
            raise InvalidPayloadError("A Slack message needs a target channel id")
        if not _text(payload, "text"):
            raise InvalidPayloadError("A Slack message needs payload.text")
    elif action_type == "email":
        if "@" not in target:
            raise InvalidPayloadError("An email needs a target address")
        if not _text(payload, "subject") or not _text(payload, "body"):
            raise InvalidPayloadError("An email needs payload.subject and payload.body")
    elif action_type in _EXTENSION_TYPES:
        _EXTENSION_TYPES[action_type](target, payload)


@dataclass(frozen=True)
class AdapterOutcome:
    """What an adapter did. ``status`` is where the row lands.

    ``executed`` means a real external effect happened. Stubs return
    ``approved`` with ``detail["state"] == "ready_to_send"`` so the row stays
    visibly un-sent until the integration is wired.
    """

    status: Literal["executed", "approved", "failed"]
    detail: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class ActionAdapter(Protocol):
    async def execute(self, action: dict[str, Any]) -> AdapterOutcome: ...
