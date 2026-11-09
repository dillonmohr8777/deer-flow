"""``propose_social_post``: draft a post for the workspace's own MomoBot page.

The post is filed in the approvals inbox as ``social_post``. It goes live on the
workspace's public MomoBot page only after an owner or admin approves it.
Nothing is posted to any outside network.
"""

from __future__ import annotations

import json

from langchain.tools import tool

from deerflow.runtime.user_context import DEFAULT_USER_ID, resolve_runtime_user_id
from deerflow.tools.types import Runtime


@tool(parse_docstring=True)
async def propose_social_post(runtime: Runtime, text: str, link: str | None = None) -> str:
    """Propose a social post for this workspace's own public MomoBot page.

    The post waits in the Approvals inbox until an owner or admin approves it; only then does it appear on the page.
    It is never posted to Google, Facebook, Instagram, LinkedIn or any other outside network, so never claim it was.
    Use only verified facts about the business; do not invent prices, dates, offers or numbers.

    Args:
        text: The exact post text the reviewer approves and the page shows.
        link: Optional http(s) link to show under the post.
    """
    from deerflow.social import ACTION_TYPE, TARGET_OWN_PAGE, global_enabled, load_settings, page_url

    if not global_enabled():
        return "Social posting is not available on this MomoBot."
    user_id = resolve_runtime_user_id(runtime)
    if not user_id or user_id == DEFAULT_USER_ID:
        return "propose_social_post requires an authenticated owner."
    from deerflow.approvals import InvalidPayloadError
    from deerflow.persistence.approvals import PendingActionRepository
    from deerflow.persistence.engine import get_session_factory
    from deerflow.persistence.organizations.identity import private_organization_id

    session_factory = get_session_factory()
    if session_factory is None:
        return "Social posting is unavailable (no database configured)."
    context = runtime.context if isinstance(runtime.context, dict) else {}
    organization_id = context.get("organization_id")
    if not isinstance(organization_id, str) or not organization_id:
        organization_id = private_organization_id(user_id)
    settings = await load_settings(session_factory, organization_id)
    if not settings.live:
        return "Social posting is turned off for this workspace. An owner or admin can turn it on in Social."
    live_page = page_url(settings.public_slug)  # computed from the slug, never stored in the proposal
    payload: dict[str, str] = {"text": text}
    if link:
        payload["link"] = link
    title = "Social post: " + " ".join(text.split())[:80]
    from deerflow.factcheck import check_for_filing
    from deerflow.tools.builtins.verify_claims_tool import _run_evidence

    refusal, fact_check, gate = check_for_filing(title, payload, _run_evidence(runtime))
    if refusal:
        return f"Not filed: the draft contradicts evidence from this run: {refusal}. Fix or remove those claims and call propose_social_post again."
    thread_id, run_id, agent = (context.get(k) for k in ("thread_id", "run_id", "agent_name"))
    repo = PendingActionRepository(session_factory)
    try:
        row = await repo.create(
            action_type=ACTION_TYPE,
            target=TARGET_OWN_PAGE,
            payload=payload,
            title=title,
            thread_id=thread_id if isinstance(thread_id, str) else None,
            run_id=run_id if isinstance(run_id, str) else None,
            agent_name=agent if isinstance(agent, str) else None,
            fact_check=fact_check,
            user_id=user_id,
            organization_id=organization_id,
        )
    except InvalidPayloadError as exc:
        return f"Not filed: {exc}. Fix the post and call propose_social_post again."
    return json.dumps(
        {
            "status": "pending_approval",
            "id": row["id"],
            "fact_check_gate": gate,
            "page_url": live_page,
            "note": f"Waiting for an owner or admin to approve it in the Approvals inbox. Once approved it appears on {live_page}. Nothing is posted outside MomoBot.",
        }
    )
