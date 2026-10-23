"""Three fixed diagnostic selectors, delegated only through a host-owned callback."""

import json
import re
from typing import Literal

from langchain.tools import tool
from pydantic import BaseModel, ConfigDict, Field

from deerflow.constants import WSL_DIAGNOSTICS_CONTEXT_KEY, WSL_DIAGNOSTICS_TOOL_NAME
from deerflow.tools.types import Runtime


class _DiagnosticInput(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)
    action: Literal["submit", "status"] = Field(description="Submit one fixed diagnostic, or read a known job's status.")
    diagnostic: Literal["true", "false", "uname"] | None = Field(default=None, description="For submit: success probe, failure probe, or kernel-name diagnostic.")
    job_id: str | None = Field(default=None, min_length=21, max_length=21, pattern=r"^momo-[0-9a-f]{16}$", description="For status only: copy the job_id returned by submission.")
    runtime: Runtime


@tool(WSL_DIAGNOSTICS_TOOL_NAME, args_schema=_DiagnosticInput)
async def wsl_diagnostic(action: Literal["submit", "status"], runtime: Runtime, diagnostic: Literal["true", "false", "uname"] | None = None, job_id: str | None = None) -> str:
    """Submit one bounded PC diagnostic or read its status in this conversation.

    true probes successful execution; false probes failed execution; uname
    requests the kernel name. Submission is asynchronous: pending means queued,
    never completed. Keep the returned job_id and check status when requested;
    do not repeatedly poll or resubmit pending/held work. Only a verified
    attached receipt establishes delivery to this conversation. No shell,
    executable, path, identity, timeout or request key is accepted.
    """
    unavailable = json.dumps({"state": "unavailable", "message": "Diagnostics are unavailable in this run."})
    context = runtime.context if runtime is not None and isinstance(runtime.context, dict) else {}
    callback = context.get(WSL_DIAGNOSTICS_CONTEXT_KEY)
    if not callable(callback) or context.get("is_subagent") or context.get("channel_name") or context.get("agent_name") != "momobot-max" or context.get("user_role") != "admin":
        return unavailable
    if action == "submit":
        if diagnostic not in ("true", "false", "uname") or job_id is not None:
            return unavailable
    elif action == "status":
        if diagnostic is not None or not isinstance(job_id, str) or re.fullmatch(r"momo-[0-9a-f]{16}", job_id) is None:
            return unavailable
    else:
        return unavailable
    tool_call_id = getattr(runtime, "tool_call_id", None)
    if not isinstance(tool_call_id, str) or not 1 <= len(tool_call_id) <= 256:
        return unavailable
    return await callback(action=action, diagnostic=diagnostic, job_id=job_id, tool_call_id=tool_call_id, current_thread_id=context.get("thread_id"), current_run_id=context.get("run_id"))
