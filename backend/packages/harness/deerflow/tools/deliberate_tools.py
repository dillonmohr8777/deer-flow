"""The ``deliberate`` fleet-agent tool: OpenRouter's Fusion panel for big-project
planning (queue item e13, ``config.deliberate``).

Gated behind the ``deliberate`` tool group in an agent's ``config.yaml``, and
opt-out just like ``team``/``exec``/``hire`` (see ``tools.py``): Momentum
staff only, same as ``team_board_tools``/``exec_seat_tools``. Two further
rules the plain staff gate doesn't cover:

- Never runs on a thread whose pinned project belongs to a client, unless a
  server-stamped owner override is present -- the panel fans the prompt out
  to several third-party providers, which MomoBot's Luna-only private-data
  lane must never see. The override is deliberately not a tool argument: an
  argument is model-chosen (or prompt-injection-chosen), so it cannot prove a
  human asked for it. ``deliberate_owner_override`` is a
  ``_SERVER_OWNED_RUNTIME_CONTEXT_KEY`` (``app/gateway/services.py``) with no
  producer yet -- until a Gateway confirmation flow stamps it, every
  client-data thread simply stays refused, which is the correct default.
- At most one call per conversational turn (deliberation is expensive),
  counted from the run's own ``runtime.state["messages"]`` rather than any
  new persistent counter, using the same genuine-user-message turn boundary
  ``ToolReceiptMiddleware`` uses.

Known gap (flagged in review, not yet closed): a custom agent config scoped
to a client (``AgentConfig.client_id``, see ``_require_run_agent_visible`` in
``app/gateway/services.py``) running on a thread with no pinned project has
no signal here at all -- ``_thread_has_client_data`` only reads the pinned
*project*'s ``client_id``. Closing it needs a new server-stamped context key
for the run's own agent-client binding, which is out of scope for this pass.

Authorization and the call cap are pure checks in ``deerflow.deliberate``;
this module resolves the facts they need (staff flag, client-data thread,
server-stamped owner override, calls already made this turn, whether the
acting agent's seat is paused per queue item e10) and makes the actual panel
call, which uses its own OpenRouter key -- never ``create_chat_model``'s
Luna/Muse-restricted model registry.
"""

from __future__ import annotations

import asyncio
import json
from typing import Literal

from langchain.tools import tool
from langchain_core.messages import AIMessage
from sqlalchemy import select

from deerflow.agents.middlewares.message_utils import is_genuine_user_message
from deerflow.config import get_app_config
from deerflow.config.app_config import AppConfig
from deerflow.deliberate import DeliberateAuthorizationError, DeliberateBudgetError, assert_call_budget, assert_can_deliberate
from deerflow.persistence.exec_seats import AgentSeatRepository
from deerflow.persistence.projects.model import ProjectRow
from deerflow.projects.context import pinned_project_snapshot
from deerflow.runtime.user_context import resolve_organization_id
from deerflow.tools.exec_seat_tools import _agent_name
from deerflow.tools.types import Runtime
from deerflow.utils.llm_text import extract_response_text

_RESULT_KEYS = ("consensus", "contradictions", "unique_insights", "blind_spots")

_ANALYST_INSTRUCTIONS = (
    "You are a deliberation panel analyst. You are given several panelists' independent answers to "
    "the same planning question. Synthesize their consensus, contradictions, unique insights and blind "
    "spots. Respond with ONLY a single JSON object on one line, no code fences, no commentary:\n"
    '{"consensus":"...","contradictions":"...","unique_insights":"...","blind_spots":"..."}'
)


def _error(message: str) -> dict:
    return {"error": message}


def _is_momentum_staff_run(runtime: Runtime | None) -> bool:
    """Read the server-stamped ``momentum_staff`` flag (never client-supplied)."""
    context = runtime.context if runtime is not None and isinstance(runtime.context, dict) else {}
    return context.get("momentum_staff") is True


def _owner_override_requested(runtime: Runtime | None) -> bool:
    """Read the server-stamped ``deliberate_owner_override`` flag (never a tool argument).

    Not honored from a model-chosen tool parameter: a fixed boolean argument
    is just as reachable by a prompt injection inside the client data itself
    as by the model's own judgment, and either way it proves nothing about
    whether a human actually asked for the override.
    """
    context = runtime.context if runtime is not None and isinstance(runtime.context, dict) else {}
    return context.get("deliberate_owner_override") is True


def _calls_completed_this_turn(messages: list, tool_name: str, current_tool_call_id: str | None) -> int:
    """Count *tool_name* tool calls already completed this conversational turn.

    Walks backward from the end of *messages*, stopping at the last genuine
    user message (``is_genuine_user_message``, the same turn boundary
    ``ToolReceiptMiddleware`` uses) rather than any ``HumanMessage`` -- a
    synthetic one (a TodoMiddleware reminder, a summarizer message) must not
    reset the cap. Within the AIMessage that made *current_tool_call_id*
    itself, only calls listed before it count as already completed: two
    parallel ``deliberate`` calls in one AIMessage must not both see the same
    "one already done" count and both refuse.
    """
    count = 0
    for message in reversed(messages or []):
        if is_genuine_user_message(message):
            break
        if not isinstance(message, AIMessage):
            continue
        calls = message.tool_calls or []
        call_ids = [call.get("id") for call in calls]
        if current_tool_call_id is not None and current_tool_call_id in call_ids:
            # The AIMessage that made the current call: only calls listed
            # before it in this same message are already completed. Calls
            # after it are parallel siblings dispatched alongside this one,
            # not prior turns' work.
            for call in calls:
                if call.get("id") == current_tool_call_id:
                    break
                if call.get("name") == tool_name:
                    count += 1
            current_tool_call_id = None  # Found; every older AIMessage counts in full below.
        else:
            count += sum(1 for call in calls if call.get("name") == tool_name)
    return count


async def _thread_has_client_data(runtime: Runtime | None) -> bool:
    """Whether the run's pinned project (if any) belongs to a client.

    Fails closed: a pinned project whose ``client_id`` can't be checked
    (no database configured) is treated as client data, the same posture
    the staff/seat checks already take on an unavailable dependency. Only a
    thread with no pinned project at all -- no signal either way -- reads as
    not client data.
    """
    snapshot = pinned_project_snapshot(runtime)
    project_id = snapshot.get("project_id") if snapshot else None
    if not project_id:
        return False
    from deerflow.persistence.engine import get_session_factory

    session_factory = get_session_factory()
    if session_factory is None:
        return True
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


async def _call_model(prompt: str, *, model: str, api_key: str, system: str | None = None) -> str:
    from langchain_openai import ChatOpenAI

    client = ChatOpenAI(model=model, api_key=api_key, base_url="https://openrouter.ai/api/v1")
    messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    response = await client.ainvoke(messages)
    return extract_response_text(getattr(response, "content", ""))


async def run_fusion_panel(prompt: str, *, panel_models: list[str], analyst_model: str, api_key: str) -> dict:
    """Fan *prompt* out to every model in *panel_models*, then synthesize their answers.

    Uses its own OpenRouter key, never ``create_chat_model``'s Luna/Muse
    model registry. Each panelist answers the same prompt independently (no
    fusion tool/plugin call exists to reach for instead), then the analyst
    model is given every panelist's actual answer -- it is never asked to
    invent opinions it was never shown. On an unparseable analyst response,
    returns its raw text as ``consensus`` with the other fields empty and
    ``fallback: True``.
    """
    panel_answers = await asyncio.gather(*(_call_model(prompt, model=model, api_key=api_key) for model in panel_models))
    transcript = "\n\n".join(f"Panelist {index + 1} ({model}):\n{answer}" for index, (model, answer) in enumerate(zip(panel_models, panel_answers, strict=True)))
    analyst_prompt = f"Planning question:\n{prompt}\n\nPanelists' answers:\n{transcript}"
    raw = await _call_model(analyst_prompt, model=analyst_model, api_key=api_key, system=_ANALYST_INSTRUCTIONS)
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
    runtime: Runtime | None = None,
    app_config: AppConfig | None = None,
) -> dict:
    config = (app_config or get_app_config()).deliberate
    if not config.enabled or not config.openrouter_api_key:
        return _error("Deliberation is not configured yet.")

    try:
        assert_can_deliberate(
            is_momentum_staff=_is_momentum_staff_run(runtime),
            thread_has_client_data=await _thread_has_client_data(runtime),
            owner_override=_owner_override_requested(runtime),
        )
    except DeliberateAuthorizationError as exc:
        return _error(str(exc))

    state = runtime.state if runtime is not None and runtime.state is not None else {}
    messages = state.get("messages") if isinstance(state, dict) else None
    current_tool_call_id = runtime.tool_call_id if runtime is not None else None
    calls_this_turn = _calls_completed_this_turn(messages or [], "deliberate", current_tool_call_id)
    try:
        assert_call_budget(calls_this_turn=calls_this_turn, max_calls_per_turn=config.max_calls_per_turn, seat_paused=await _seat_paused(runtime))
    except DeliberateBudgetError as exc:
        return _error(str(exc))

    panel_models = config.quality_panel_models if preset == "quality" else config.cheap_panel_models
    return await run_fusion_panel(prompt, panel_models=panel_models, analyst_model=config.analyst_model, api_key=config.openrouter_api_key)


@tool(parse_docstring=True)
async def deliberate(
    prompt: str,
    runtime: Runtime,
    preset: Literal["cheap", "quality"] = "cheap",
) -> dict:
    """Run OpenRouter's Fusion deliberation panel for big-project planning.

    A panel of models plus an analyst returns consensus, contradictions,
    unique insights and blind spots. Momentum-staff only; refused on a
    thread whose pinned project belongs to a client -- there is no argument
    that overrides this, since only a server-stamped confirmation (not a
    caller-chosen value) can prove a human authorized it. At most one call
    per turn. Off until ``config.deliberate.enabled`` and an OpenRouter key
    are set.

    Args:
        prompt: The planning question or brief to deliberate on.
        runtime: Injected tool runtime.
        preset: "cheap" or "quality" panel.

    Returns:
        {"consensus", "contradictions", "unique_insights", "blind_spots"}, or {"error": ...}.
    """
    return await _deliberate_impl(prompt, preset=preset, runtime=runtime)
