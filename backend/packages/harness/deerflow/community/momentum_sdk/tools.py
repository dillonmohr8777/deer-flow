"""Model-facing wrapper for the worker-owned offline review capability."""

import json

from langchain.tools import tool

from deerflow.constants import MOMENTUM_SDK_CONTEXT_KEY
from deerflow.runtime.user_context import resolve_runtime_user_id
from deerflow.tools.types import Runtime


@tool("momentum_sdk_draft", parse_docstring=True)
async def momentum_sdk_draft(client_id: str, request: str, runtime: Runtime) -> str:
    """Prepare a synthetic offline typed review; never perform client work.

    The host authorizes exact canonical IDs and binds this tool to the active
    owner, thread, and run. Results are drafts, not verified deliverables.

    Args:
        client_id: Exact canonical client identifier authorized by the host.
        request: Bounded local review request, at most 8000 characters.
        runtime: Injected host capability and authenticated run context.

    Returns:
        A typed synthetic draft packet or a sanitized error.
    """
    context = runtime.context if runtime is not None and isinstance(runtime.context, dict) else {}
    reviewer = context.get(MOMENTUM_SDK_CONTEXT_KEY)
    if context.get("is_subagent") or not callable(reviewer):
        return json.dumps({"error": "Offline review unavailable for this run or subagent."})
    try:
        return await reviewer(client_id=client_id, request=request, user_id=resolve_runtime_user_id(runtime), thread_id=context.get("thread_id"), run_id=context.get("run_id"))
    except Exception:
        return json.dumps({"error": "Offline review failed; no external action performed."})
