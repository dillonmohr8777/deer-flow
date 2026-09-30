"""The ``deliberate`` fleet-agent tool: OpenRouter's Fusion panel for big-project
planning (queue item e13, ``config.deliberate``).

Gated behind the ``deliberate`` tool group in an agent's ``config.yaml``, and
opt-out just like ``team``/``exec``/``hire`` (see ``tools.py``): Momentum
staff only, same as ``team_board_tools``/``exec_seat_tools``. Two further
rules the plain staff gate doesn't cover:

- Never runs on a thread whose pinned project belongs to a client, unless a
  verified organization owner/admin overrides it -- the panel fans the
  prompt out to several third-party providers, which MomoBot's Luna-only
  private-data lane must never see.
- At most one call per conversational turn (deliberation is expensive),
  counted from the run's own ``runtime.state["messages"]`` rather than any
  new persistent counter.

Authorization and the call cap are pure checks in ``deerflow.deliberate``;
this module resolves the facts they need (staff flag, client-data thread,
verified owner override, calls already made this turn, whether the acting
agent's seat is paused per queue item e10) and makes the actual panel call,
which uses its own OpenRouter key -- never ``create_chat_model``'s
Luna/Muse-restricted model registry.
"""

from __future__ import annotations

import json
from typing import Literal

from langchain.tools import tool
from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import select

from deerflow.config import get_app_config
from deerflow.config.app_config import AppConfig
from deerflow.deliberate import DeliberateAuthorizationError, DeliberateBudgetError, assert_call_budget, assert_can_deliberate
from deerflow.persistence.exec_seats import AgentSeatRepository
from deerflow.persistence.projects.model import ProjectRow
from deerflow.projects.context import pinned_project_snapshot
from deerflow.runtime.user_context import resolve_organization_id, resolve_runtime_actor_user_id
from deerflow.tools.exec_seat_tools import _agent_name, _is_active_org_admin
from deerflow.tools.types import Runtime
from deerflow.utils.llm_text import extract_response_text

_RESULT_KEYS = ("consensus", "contradictions", "unique_insights", "blind_spots")


def _error(message: str) -> dict:
    return {"error": message}


def _is_momentum_staff_run(runtime: Runtime | None) -> bool:
    """Read the server-stamped ``momentum_staff`` flag (never client-supplied)."""
    context = runtime.context if runtime is not None and isinstance(runtime.context, dict) else {}
    return context.get("momentum_staff") is True


def _calls_including_current(messages: list, tool_name: str) -> int:
    """Count *tool_name* tool calls in AIMessages since the last HumanMessage.

    Includes the AIMessage currently invoking this tool -- LangGraph appends
    it to state before dispatching to tools -- so a caller wanting the count
    of calls already *completed* this turn subtracts 1.
    """
    count = 0
    for message in reversed(messages or []):
        if isinstance(message, HumanMessage):
            break
        if isinstance(message, AIMessage):
            for call in message.tool_calls or []:
                if call.get("name") == tool_name:
                    count += 1
    return count


async def _thread_has_client_data(runtime: Runtime | None) -> bool:
    """Whether the run's pinned project (if any) belongs to a client."""
    snapshot = pinned_project_snapshot(runtime)
    project_id = snapshot.get("project_id") if snapshot else None
    if not project_id:
        return False
    from deerflow.persistence.engine import get_session_factory

    session_factory = get_session_factory()
    if session_factory is None:
        return False
    async with session_factory() as session:
        result = await session.execute(select(ProjectRow.client_id).where(ProjectRow.id == project_id))
        client_id = result.scalar_one_or_none()
    return client_id is not None


async def _seat_paused(runtime: Runtime | None) -> bool:
    """Whether the acting agent currently holds a paused seat (queue item e10)."""
    if resolve_organization_id() is None:
        return False
    from deerflow.persistence.engine import get_session_factory

    session_factory = get_session_factory()
    if session_factory is None:
        return False
    repo = AgentSeatRepository(session_factory)
    paused = await repo.paused_seat_for_agent(_agent_name(runtime))
    return paused is not None


async def run_fusion_panel(prompt: str, *, model: str, api_key: str) -> dict:
    """Call OpenRouter's Fusion deliberation panel and return its verdict.

    Uses its own OpenRouter key, never ``create_chat_model``'s Luna/Muse
    model registry -- the panel fans the prompt out to several third-party
    providers. On an unparseable response, returns the raw text as
    ``consensus`` with the other fields empty and ``fallback: True``.
    """
    from langchain_openai import ChatOpenAI

    client = ChatOpenAI(model=model, api_key=api_key, base_url="https://openrouter.ai/api/v1")
    instructions = (
        "You are a deliberation panel analyst reviewing several models' independent takes on a "
        "planning question. Respond with ONLY a single JSON object on one line, no code fences, "
        "no commentary:\n"
        '{"consensus":"...","contradictions":"...","unique_insights":"...","blind_spots":"..."}'
    )
    response = await client.ainvoke([{"role": "system", "content": instructions}, {"role": "user", "content": prompt}])
    raw = extract_response_text(getattr(response, "content", ""))
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        parsed = None
    if isinstance(parsed, dict) and all(key in parsed for key in _RESULT_KEYS):
        return {key: str(parsed[key]) for key in _RESULT_KEYS}
    return {"consensus": raw, "contradictions": "", "unique_insights": "", "blind_spots": "", "fallback": True}


async def _deliberate_impl(
    prompt: str,
    *,
    preset: Literal["cheap", "quality"] = "cheap",
    override_client_data_refusal: bool = False,
    runtime: Runtime | None = None,
    app_config: AppConfig | None = None,
) -> dict:
    config = (app_config or get_app_config()).deliberate
    if not config.enabled or not config.openrouter_api_key:
        return _error("Deliberation is not configured yet.")

    owner_override = False
    if override_client_data_refusal:
        actor_user_id = resolve_runtime_actor_user_id(runtime)
        owner_override = actor_user_id is not None and await _is_active_org_admin(actor_user_id)
    try:
        assert_can_deliberate(
            is_momentum_staff=_is_momentum_staff_run(runtime),
            thread_has_client_data=await _thread_has_client_data(runtime),
            owner_override=owner_override,
        )
    except DeliberateAuthorizationError as exc:
        return _error(str(exc))

    state = runtime.state if runtime is not None and runtime.state is not None else {}
    messages = state.get("messages") if isinstance(state, dict) else None
    calls_this_turn = max(_calls_including_current(messages or [], "deliberate") - 1, 0)
    try:
        assert_call_budget(calls_this_turn=calls_this_turn, max_calls_per_turn=config.max_calls_per_turn, seat_paused=await _seat_paused(runtime))
    except DeliberateBudgetError as exc:
        return _error(str(exc))

    model = config.quality_model if preset == "quality" else config.cheap_model
    return await run_fusion_panel(prompt, model=model, api_key=config.openrouter_api_key)


@tool(parse_docstring=True)
async def deliberate(
    prompt: str,
    runtime: Runtime,
    preset: Literal["cheap", "quality"] = "cheap",
    override_client_data_refusal: bool = False,
) -> dict:
    """Run OpenRouter's Fusion deliberation panel for big-project planning.

    A panel of models plus an analyst returns consensus, contradictions,
    unique insights and blind spots. Momentum-staff only; refused on a
    thread whose pinned project belongs to a client unless an organization
    owner/admin sets ``override_client_data_refusal`` (verified server-side,
    not merely because the caller asked). At most one call per turn. Off
    until ``config.deliberate.enabled`` and an OpenRouter key are set.

    Args:
        prompt: The planning question or brief to deliberate on.
        runtime: Injected tool runtime.
        preset: "cheap" or "quality" panel model.
        override_client_data_refusal: An organization owner's explicit override to run on a client-data thread.

    Returns:
        {"consensus", "contradictions", "unique_insights", "blind_spots"}, or {"error": ...}.
    """
    return await _deliberate_impl(prompt, preset=preset, override_client_data_refusal=override_client_data_refusal, runtime=runtime)
