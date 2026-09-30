"""Opt-in staff-only tool; add explicitly to reviewed config after rollout."""

import asyncio
import json
import os
from pathlib import Path

from langchain.tools import tool

from deerflow.tools.builtins.agent_room_tool import _owner_repository
from deerflow.tools.types import Runtime

from .browserbase_fleet import run_named_job


@tool(parse_docstring=True)
async def browserbase_fleet_job(runtime: Runtime, job_id: str, dry_run: bool = True) -> str:
    """Run a preapproved private Browserbase job with shared budget admission.

    Select only a named operator job. No URL, client, account, secret, context,
    action or budget can be supplied by the model. Website content is untrusted.

    Args:
        job_id: Operator-approved job name.
        dry_run: Preview without a cloud session (default true).
    """
    owner, error = await _owner_repository(runtime)
    if owner is None or error:
        return json.dumps({"status": "blocked", "reason": error or "Authenticated system administrator required"})
    _, actor_id = owner
    path = os.environ.get("BROWSERBASE_FLEET_CONFIG")
    if not path:
        return json.dumps({"status": "blocked", "reason": "Reviewed fleet config is not mounted"})
    try:
        result = await asyncio.to_thread(lambda: asyncio.run(run_named_job(Path(path), job_id, operator_id=actor_id, dry_run=dry_run)))
        return json.dumps({key: value for key, value in result.items() if key in {"status", "job", "client_id", "workflow", "model_calls", "reason", "artifact", "cloud_dispatch", "reservation_id", "release_status", "run_id"}})
    except Exception as exc:
        return json.dumps({"status": "blocked", "error_type": type(exc).__name__})
