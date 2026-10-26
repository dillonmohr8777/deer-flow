"""Canonical serialization for LangChain / LangGraph objects.

Provides a single source of truth for converting LangChain message
objects, Pydantic models, and LangGraph state dicts into plain
JSON-serialisable Python structures.

Consumers: ``deerflow.runtime.runs.worker`` (SSE publishing) and
``app.gateway.routers.threads`` (REST responses).
"""

from __future__ import annotations

import re
from typing import Any


def serialize_lc_object(obj: Any) -> Any:
    """Recursively serialize a LangChain object to a JSON-serialisable dict."""
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {k: serialize_lc_object(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [serialize_lc_object(item) for item in obj]
    # Pydantic v2
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump()
        except Exception:
            pass
    # Pydantic v1 / older objects
    if hasattr(obj, "dict"):
        try:
            return obj.dict()
        except Exception:
            pass
    # Interrupt is a __slots__ class — no model_dump/dict/__dict__, so it
    # would reach str() and produce a malformed payload.
    try:
        from langgraph.types import Interrupt
    except ImportError:
        pass
    else:
        if isinstance(obj, Interrupt):
            return serialize_lc_object(
                {
                    "value": obj.value,
                    "id": getattr(obj, "id", None),
                }
            )
    # Last resort
    try:
        return str(obj)
    except Exception:
        return repr(obj)


def serialize_channel_values(channel_values: dict[str, Any]) -> dict[str, Any]:
    """Serialize channel values, stripping internal LangGraph keys.

    Only ``__pregel_*`` keys are removed — ``__interrupt__`` is deliberately
    preserved so the LangGraph SDK can detect interrupt events from values
    chunks (see issue #3595).
    """
    result: dict[str, Any] = {}
    for key, value in channel_values.items():
        if key.startswith("__pregel_"):
            continue
        result[key] = serialize_lc_object(value)
    return result


def strip_data_url_image_blocks(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove ``data:``-scheme ``image_url`` blocks from *hide_from_ui* messages.

    The history and run-wait endpoints return checkpoint-persisted messages to
    the frontend.  ``ViewImageMiddleware`` now keeps its base64 image payloads
    inside the model request, but threads checkpointed by earlier versions still
    hold them in ``hide_from_ui`` human messages — these are internal model
    context and must not be sent over the wire (huge response bodies, no UI
    value).

    Only content blocks of type ``image_url`` whose URL starts with ``data:``
    are stripped.  Text blocks, ``https://`` image URLs, and non-hidden
    messages are left untouched so that message ordering and count are
    preserved.
    """
    result: list[dict[str, Any]] = []
    for msg in messages:
        if not isinstance(msg, dict):
            result.append(msg)
            continue

        # Only touch messages explicitly flagged as hidden from the UI.
        additional_kwargs = msg.get("additional_kwargs")
        if not (isinstance(additional_kwargs, dict) and additional_kwargs.get("hide_from_ui") is True):
            result.append(msg)
            continue

        content = msg.get("content")
        if not isinstance(content, list):
            result.append(msg)
            continue

        # Filter out image_url blocks with data: scheme.
        filtered = [block for block in content if not (isinstance(block, dict) and block.get("type") == "image_url" and isinstance(block.get("image_url"), dict) and str(block["image_url"].get("url", "")).startswith("data:"))]
        result.append({**msg, "content": filtered})
    return result


def serialize_channel_values_for_api(channel_values: dict[str, Any]) -> dict[str, Any]:
    """Serialize channel values and strip base64 image data from messages.

    Convenience wrapper combining :func:`serialize_channel_values` with
    :func:`strip_data_url_image_blocks`.  Use this in all REST endpoints
    that return channel values to the frontend so that ``data:``-scheme
    base64 image payloads are never sent over the wire.
    """
    result = scrub_private_memory(serialize_channel_values(channel_values))
    if isinstance(result.get("messages"), list):
        result["messages"] = strip_data_url_image_blocks(result["messages"])
    return result


# Mirror deerflow.agents.memory.scope's STAFF_MEMORY_PROVENANCE_KEY and STAFF_MEMORY_SCOPE_KEY
# (runtime must not import agents): the scope hash and the run's scope binding.
_PRIVATE_SCOPE_KEYS = frozenset({"deerflow_memory_scope", "__deerflow_staff_memory_scope"})


# Rows persisted before write-time scrubbing hold messages stringified by json.dumps(default=str).
_STRINGIFIED_MEMORY = re.compile(r"\bid='[^']*__memory'")


def _is_private_memory(value: Any) -> bool:
    if isinstance(value, str):
        return bool(_STRINGIFIED_MEMORY.search(value))
    return isinstance(value, dict) and "content" in value and str(value.get("id") or "").endswith("__memory")


def scrub_private_memory(value: Any) -> Any:
    """Drop ``<id>__memory`` reminders and staff scope hashes from serialized output.

    The memory reminder carries one staff member's private memory and the scope
    hash names their bucket; workspace teammates can read the same thread state
    and stream, so neither may leave the server in any stream mode or snapshot.
    A bare memory chunk (``messages`` mode) keeps its id but loses its content.
    """
    if isinstance(value, list):
        return [scrub_private_memory(item) for item in value if not _is_private_memory(item)]
    if isinstance(value, dict):
        if _is_private_memory(value):
            return {**value, "content": "", "additional_kwargs": {}}
        return {key: scrub_private_memory(item) for key, item in value.items() if key not in _PRIVATE_SCOPE_KEYS}
    return value


def serialize_messages_tuple(obj: Any) -> Any:
    """Serialize a messages-mode tuple ``(chunk, metadata)``."""
    if isinstance(obj, tuple) and len(obj) == 2:
        chunk, metadata = obj
        return [serialize_lc_object(chunk), metadata if isinstance(metadata, dict) else {}]
    return serialize_lc_object(obj)


def serialize(obj: Any, *, mode: str = "") -> Any:
    """Serialize LangChain objects with mode-specific handling.

    * ``messages`` — obj is ``(message_chunk, metadata_dict)``
    * ``values`` — obj is the full state dict; ``__pregel_*`` keys stripped and
      base64 ``data:`` image blocks dropped from hide_from_ui messages
    * everything else — recursive ``model_dump()`` / ``dict()`` fallback
    """
    if mode == "messages":
        frame = serialize_messages_tuple(obj)
        if isinstance(frame, list) and len(frame) == 2:
            # Keep the [chunk, metadata] shape; a private chunk is blanked, not removed.
            return [scrub_private_memory(frame[0]), scrub_private_memory(frame[1])]
        return scrub_private_memory(frame)
    if mode == "values" and isinstance(obj, dict):
        # ``values`` snapshots stream the full state to the frontend, so they
        # must drop base64 image payloads the same way the REST endpoints do.
        return serialize_channel_values_for_api(obj)
    return scrub_private_memory(serialize_lc_object(obj))
