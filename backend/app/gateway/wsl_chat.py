"""Authenticated, run-bound chat access to the existing non-executing bridge."""

from __future__ import annotations

import asyncio
import hashlib
import json

from fastapi import HTTPException

from app.gateway.auth_disabled import AUTH_SOURCE_INTERNAL, AUTH_SOURCE_PAT, AUTH_SOURCE_SESSION
from app.gateway.internal_auth import get_trusted_internal_owner_user_id
from app.gateway.routers.wsl_diagnostics import DiagnosticRequest, _identity, enqueue_diagnostic, read_diagnostic
from app.gateway.wsl_bridge import BridgeError, BridgeStore
from deerflow.config.builtin_agents import MOMOBOT_MAX_NAME

_DIAGNOSTICS = {"true": ["/usr/bin/true"], "false": ["/usr/bin/false"], "uname": ["/usr/bin/uname", "-s"]}
_UNAVAILABLE = '{"state":"unavailable","message":"Diagnostics are unavailable for this request."}'


def _authority(request, internal_owner_user):
    auth = _identity(request)
    source = getattr(request.state, "auth_source", None)
    if source not in (AUTH_SOURCE_SESSION, AUTH_SOURCE_PAT, AUTH_SOURCE_INTERNAL):
        return None
    user = internal_owner_user if source == AUTH_SOURCE_INTERNAL else auth.user
    if getattr(user, "system_role", None) != "admin" or str(getattr(user, "id", "")) != auth.actor_user_id:
        return None
    if source == AUTH_SOURCE_INTERNAL and get_trusted_internal_owner_user_id(request) != auth.storage_user_id:
        return None
    if not all(auth.has_permission("threads", permission) for permission in ("read", "write")):
        return None
    return source, auth.organization_id, auth.actor_user_id, auth.storage_user_id


def _summary(result):
    state = result["state"]
    output = {
        "job_id": result["job_id"],
        "state": "pending" if state in ("queued", "claimed") else state,
        "artifact_available": result["attached"],
    }
    receipt = result["receipt"]
    if receipt is not None:
        output["receipt"] = {
            name: receipt[name]
            for name in (
                "state",
                "exit_code",
                "duration_seconds",
                "limits_applied",
                "stdout_bytes",
                "stderr_bytes",
                "stdout_truncated",
                "stderr_truncated",
            )
        }
    if output["state"] == "pending":
        output["message"] = "Submitted to the existing worker; execution is pending. Check status later with this job_id."
    elif result["attached"]:
        output["message"] = "The verified diagnostic receipt is attached to this conversation."
    elif state in ("done", "failed"):
        output["message"] = "A verified receipt is available; attachment to this conversation is pending."
    else:
        output["message"] = "The original request requires reconciliation; do not submit it again."
    return json.dumps(output, separators=(",", ":"))


async def prepare_wsl_diagnostics(*, request, config, app_config, thread_id, run_id, internal_owner_user=None):
    """Bind only an admitted Momo admin lead, never caller-provided identity fields."""
    context = {}
    for section in ("configurable", "context"):
        if isinstance(config.get(section), dict):
            context.update(config[section])
    if context.get("agent_name") != MOMOBOT_MAX_NAME or context.get("is_bootstrap") or context.get("is_subagent") or context.get("channel_name") or not app_config.momobot_max.enabled:
        return None
    try:
        authority = _authority(request, internal_owner_user)
        if authority is None:
            return None
        # This validates the existing deployment flag/root but opens no spool or queue.
        await asyncio.to_thread(BridgeStore.from_environment)
    except (HTTPException, BridgeError, OSError):
        return None

    async def diagnostic(*, action, diagnostic, job_id, tool_call_id, current_thread_id, current_run_id):
        try:
            if _authority(request, internal_owner_user) != authority or current_thread_id != thread_id or current_run_id != run_id or not isinstance(tool_call_id, str) or not 1 <= len(tool_call_id) <= 256:
                return _UNAVAILABLE
            if action == "submit" and diagnostic in _DIAGNOSTICS and job_id is None:
                # A retry of the same logical ToolCall keeps its server-run-scoped key.
                key = hashlib.sha256(json.dumps(["momo-chat-v1", run_id, tool_call_id], separators=(",", ":")).encode()).hexdigest()
                body = DiagnosticRequest(request_id="chat-" + key, argv=_DIAGNOSTICS[diagnostic], timeout=30)
                result = await enqueue_diagnostic(thread_id=thread_id, request=request, body=body)
            elif action == "status" and diagnostic is None and isinstance(job_id, str):
                result = await read_diagnostic(thread_id=thread_id, job_id=job_id, request=request)
            else:
                return _UNAVAILABLE
            return _summary(result)
        except HTTPException as exc:
            if exc.status_code == 409:
                return '{"state":"held","message":"The original diagnostic requires reconciliation; do not resubmit it."}'
            return _UNAVAILABLE

    return diagnostic
