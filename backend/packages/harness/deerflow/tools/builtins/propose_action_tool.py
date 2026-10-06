"""``propose_action``: the only way an agent asks to send something outbound.

The tool never sends. It files a pending row in the owner's approvals inbox;
a human edits and approves it there, and only then does an executor run.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from langchain.tools import tool

from deerflow.runtime.user_context import DEFAULT_USER_ID, resolve_runtime_user_id
from deerflow.tools.types import Runtime


@tool(parse_docstring=True)
async def propose_action(
    runtime: Runtime,
    action_type: Literal["slack_message", "email", "ad_change", "other"],
    title: str,
    target: str,
    payload: dict[str, Any],
) -> str:
    """Propose an outbound action for human approval. Use this instead of sending anything yourself.

    Nothing is sent or changed until the owner approves it in the Approvals inbox.
    After calling this, tell the user it is waiting for approval; never claim it was sent.

    Args:
        action_type: slack_message (target = Slack channel id, payload.text), email (target = recipient address, payload.subject and payload.body), ad_change (target = account/campaign, payload = the exact change), or other.
        title: One-line summary the reviewer sees in the inbox.
        target: Where it goes: a Slack channel id, an email address, or an ad account/campaign.
        payload: The exact content to send or apply. The reviewer may edit it before approving.
    """
    user_id = resolve_runtime_user_id(runtime)
    if not user_id or user_id == DEFAULT_USER_ID:
        return "propose_action requires an authenticated owner."
    from deerflow.approvals import InvalidPayloadError
    from deerflow.persistence.approvals import PendingActionRepository
    from deerflow.persistence.engine import get_session_factory

    session_factory = get_session_factory()
    if session_factory is None:
        return "The approvals inbox is unavailable (no database configured)."
    from deerflow.factcheck import verify_draft
    from deerflow.tools.builtins.verify_claims_tool import _run_evidence

    # Claim-check the exact text the human will approve, against this run's tool outputs.
    draft = "\n".join(v for v in (title, *payload.values()) if isinstance(v, str)) if isinstance(payload, dict) else title
    report = verify_draft(draft, _run_evidence(runtime))
    if report.blocked:
        bad = [c for c in report.to_dict()["claims"] if c["verdict"] == "contradicted"]
        return "Not filed: the draft contradicts evidence from this run: " + "; ".join(f'"{c["text"]}" ({c["reason"]})' for c in bad) + ". Fix or remove those claims and call propose_action again."
    fact_check = report.to_dict() if report.claims else None
    context = runtime.context if isinstance(runtime.context, dict) else {}
    thread_id, run_id, agent = (context.get(k) for k in ("thread_id", "run_id", "agent_name"))
    try:
        row = await PendingActionRepository(session_factory).create(
            action_type=action_type,
            target=target,
            payload=payload,
            title=title,
            thread_id=thread_id if isinstance(thread_id, str) else None,
            run_id=run_id if isinstance(run_id, str) else None,
            agent_name=agent if isinstance(agent, str) else None,
            fact_check=fact_check,
            user_id=user_id,
        )
    except InvalidPayloadError as exc:
        return f"Not filed: {exc}. Fix the proposal and call propose_action again."
    return json.dumps({"status": "pending_approval", "id": row["id"], "fact_check_gate": report.gate, "note": "Waiting for the owner to approve in the Approvals inbox. Nothing has been sent."})
