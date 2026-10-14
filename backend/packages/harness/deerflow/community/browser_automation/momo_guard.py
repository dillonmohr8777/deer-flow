"""Private client-browser authentication, selected only from trusted run context."""
import os
import time
import uuid
from collections.abc import Mapping

from langchain_core.tools import ToolException

# isort: split

from deerflow.community.browser_automation.momo_protocol import (
    SERVER,
    canonical,
    signature,
    valid_scope,
)
from deerflow.runtime.user_context import resolve_runtime_actor_user_id


def build_private_client_guard():
    async def guard(request, handler):
        if request.server_name != SERVER:
            return await handler(request)
        runtime = getattr(request, "runtime", None)
        if runtime is None:
            from langgraph.runtime import get_runtime
            runtime = get_runtime()
        context = getattr(runtime, "context", None)
        if not isinstance(context, Mapping):
            raise ToolException("Saved client browsers require Dillon's private workspace.")
        scope = {
            "actor": resolve_runtime_actor_user_id(runtime),
            "storage": context.get("storage_user_id"),
            "organization": context.get("organization_id"),
            "thread": context.get("thread_id"),
        }
        if not valid_scope(scope):
            raise ToolException("Saved client browsers are available only in Dillon's private workspace.")
        secret = os.environ.get("BRAIN_MCP_AUTHORIZATION", "")
        if not secret.startswith("Bearer ") or not secret[7:]:
            raise ToolException("Private browser authentication is unavailable.")
        nonce, issued = uuid.uuid4().hex, str(int(time.time()))
        headers = dict(request.headers or {})
        headers.update({
            "X-Momo-Scope": canonical(scope), "X-Momo-Nonce": nonce, "X-Momo-Issued": issued,
            "X-Momo-Signature": signature(secret, scope, nonce, issued, request.name, request.args),
        })
        return await handler(request.override(headers=headers))
    return guard
