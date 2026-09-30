"""Tests for the fleet-agent ``deliberate`` tool (queue item e13, OpenRouter Fusion panel).

Covers the accept bar named in QUEUE.md plus review follow-ups: the
Momentum-staff-only gate, the client-data refusal (and its server-stamped
owner override -- never a tool argument), the budget cap (a paused seat per
queue item e10), one call per conversational turn (robust to synthetic
HumanMessages and to parallel calls in one AIMessage), a fail-closed
client-data check when the database is unavailable, and the panel actually
fanning out to every configured model before the analyst runs. Pure
authorization/budget logic is covered by ``test_deliberate_workflow.py``;
this file is the tool layer that resolves the facts those checks need and
calls the (monkeypatched) panel.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from org_isolation_fixtures import ORG_S, USER_A, acting_as, org_world  # noqa: F401

from deerflow.config.deliberate_config import DeliberateConfig
from deerflow.persistence.exec_seats import AgentSeatRepository
from deerflow.persistence.projects.model import ProjectRow
from deerflow.runtime.context_keys import PROJECT_CONTEXT_KEY
from deerflow.tools.deliberate_tools import _deliberate_impl, run_fusion_panel


class _DummyRuntime(SimpleNamespace):
    context: dict
    state: dict | None
    tool_call_id: str | None


def _runtime(
    *,
    momentum_staff: bool = True,
    agent_name: str | None = None,
    project_id: str | None = None,
    owner_override: bool = False,
    messages: list | None = None,
    tool_call_id: str | None = "current-call",
) -> _DummyRuntime:
    context: dict = {"momentum_staff": momentum_staff}
    if agent_name is not None:
        context["agent_name"] = agent_name
    if project_id is not None:
        context[PROJECT_CONTEXT_KEY] = {"project_id": project_id, "name": "", "instructions": ""}
    if owner_override:
        context["deliberate_owner_override"] = True
    return _DummyRuntime(context=context, state={"messages": messages or []}, tool_call_id=tool_call_id)


def _config(**overrides) -> SimpleNamespace:
    return SimpleNamespace(deliberate=DeliberateConfig(enabled=True, openrouter_api_key="test-key", **overrides))


async def _add_project(session_factory, *, project_id: str, user_id: str, client_id: str | None) -> None:
    async with session_factory() as session, session.begin():
        session.add(ProjectRow(id=project_id, user_id=user_id, client_id=client_id, name="p", instructions=""))


@pytest.fixture(autouse=True)
def _stub_fusion_panel(monkeypatch):
    async def fake_run_fusion_panel(prompt, *, panel_models, analyst_model, api_key):
        fake_run_fusion_panel.calls.append((prompt, panel_models, analyst_model, api_key))
        return {"consensus": "c", "contradictions": "", "unique_insights": "", "blind_spots": ""}

    fake_run_fusion_panel.calls = []
    monkeypatch.setattr("deerflow.tools.deliberate_tools.run_fusion_panel", fake_run_fusion_panel)
    return fake_run_fusion_panel


# --- config / staff gate ---


@pytest.mark.asyncio
async def test_disabled_config_refuses(org_world):  # noqa: F811
    with acting_as(USER_A, ORG_S):
        result = await _deliberate_impl("plan it", runtime=_runtime(), app_config=SimpleNamespace(deliberate=DeliberateConfig()))
    assert result == {"error": "Deliberation is not configured yet."}


@pytest.mark.asyncio
async def test_refuses_without_momentum_staff_flag(org_world):  # noqa: F811
    with acting_as(USER_A, ORG_S):
        result = await _deliberate_impl("plan it", runtime=_runtime(momentum_staff=False), app_config=_config())
    assert result == {"error": "Deliberation is restricted to Momentum staff."}


@pytest.mark.asyncio
async def test_staff_call_with_no_project_reaches_the_panel(org_world, _stub_fusion_panel):  # noqa: F811
    with acting_as(USER_A, ORG_S):
        result = await _deliberate_impl("plan it", runtime=_runtime(), app_config=_config())
    assert result == {"consensus": "c", "contradictions": "", "unique_insights": "", "blind_spots": ""}
    assert _stub_fusion_panel.calls == [("plan it", ["openrouter/auto"], "openrouter/auto", "test-key")]


# --- client-data refusal: server-stamped override only, never a tool argument ---


@pytest.mark.asyncio
async def test_client_data_thread_refuses_without_override(org_world):  # noqa: F811
    session_factory = org_world
    await _add_project(session_factory, project_id="proj-1", user_id=USER_A, client_id="client-1")
    with acting_as(USER_A, ORG_S):
        result = await _deliberate_impl("plan it", runtime=_runtime(project_id="proj-1"), app_config=_config())
    assert result == {"error": ("This thread carries client data. The deliberation panel sends the prompt to several outside providers, outside MomoBot's Luna-only private-data lane, so an organization owner must override to run it here.")}


@pytest.mark.asyncio
async def test_client_data_thread_allowed_with_the_server_stamped_override(org_world, _stub_fusion_panel):  # noqa: F811
    session_factory = org_world
    await _add_project(session_factory, project_id="proj-1", user_id=USER_A, client_id="client-1")
    with acting_as(USER_A, ORG_S):
        result = await _deliberate_impl("plan it", runtime=_runtime(project_id="proj-1", owner_override=True), app_config=_config())
    assert "error" not in result
    assert _stub_fusion_panel.calls


@pytest.mark.asyncio
async def test_a_model_chosen_override_argument_no_longer_exists(org_world):  # noqa: F811
    """Review finding: the override must not be a tool argument the model (or an
    injected prompt) can set on any admin's run. There is now no such
    parameter on ``_deliberate_impl`` at all -- passing it would be a
    TypeError, not a bypass."""
    with pytest.raises(TypeError):
        await _deliberate_impl("plan it", override_client_data_refusal=True, runtime=_runtime(), app_config=_config())  # type: ignore[call-arg]


# --- budget cap: paused seat (queue item e10) ---


@pytest.mark.asyncio
async def test_paused_seat_refuses_the_call(org_world):  # noqa: F811
    session_factory = org_world
    with acting_as(USER_A, ORG_S):
        repo = AgentSeatRepository(session_factory)
        seat = await repo.claim_seat(seat="CMO", agent_name="cmo-agent", weekly_token_budget=100)
        await repo.set_paused(seat["id"], paused=True)

        result = await _deliberate_impl("plan it", runtime=_runtime(agent_name="cmo-agent"), app_config=_config())
    assert result == {"error": "This seat is over its weekly token budget; deliberation is paused until it resets."}


# --- one call per turn ---


@pytest.mark.asyncio
async def test_second_call_in_the_same_turn_is_refused(org_world, _stub_fusion_panel):  # noqa: F811
    prior_ai_message = AIMessage(content="", tool_calls=[{"name": "deliberate", "args": {}, "id": "call-1"}])
    second_ai_message = AIMessage(content="", tool_calls=[{"name": "deliberate", "args": {}, "id": "call-2"}])
    messages = [HumanMessage(content="plan the big migration"), prior_ai_message, ToolMessage(content="ok", tool_call_id="call-1"), second_ai_message]

    with acting_as(USER_A, ORG_S):
        result = await _deliberate_impl("plan it again", runtime=_runtime(messages=messages, tool_call_id="call-2"), app_config=_config())
    assert result == {"error": "Deliberation is limited to 1 call(s) per turn."}
    assert _stub_fusion_panel.calls == []


@pytest.mark.asyncio
async def test_a_second_turn_after_a_new_human_message_is_allowed(org_world, _stub_fusion_panel):  # noqa: F811
    prior_ai_message = AIMessage(content="", tool_calls=[{"name": "deliberate", "args": {}, "id": "call-1"}])
    new_ai_message = AIMessage(content="", tool_calls=[{"name": "deliberate", "args": {}, "id": "call-2"}])
    messages = [
        HumanMessage(content="plan the big migration"),
        prior_ai_message,
        ToolMessage(content="ok", tool_call_id="call-1"),
        HumanMessage(content="now plan the next one"),
        new_ai_message,
    ]

    with acting_as(USER_A, ORG_S):
        result = await _deliberate_impl("plan the next one", runtime=_runtime(messages=messages, tool_call_id="call-2"), app_config=_config())
    assert "error" not in result


@pytest.mark.asyncio
async def test_a_synthetic_reminder_message_does_not_reset_the_turn_cap(org_world, _stub_fusion_panel):  # noqa: F811
    """Review finding: a hidden framework message (a TodoMiddleware reminder, a
    summarizer message) is still a ``HumanMessage`` but is not a genuine user
    turn boundary -- ``is_genuine_user_message`` returns False for it, unlike
    the old bare ``isinstance(message, HumanMessage)`` check."""
    prior_ai_message = AIMessage(content="", tool_calls=[{"name": "deliberate", "args": {}, "id": "call-1"}])
    synthetic_reminder = HumanMessage(content="<system-reminder>...</system-reminder>", additional_kwargs={"hide_from_ui": True})
    second_ai_message = AIMessage(content="", tool_calls=[{"name": "deliberate", "args": {}, "id": "call-2"}])
    messages = [HumanMessage(content="plan the big migration"), prior_ai_message, ToolMessage(content="ok", tool_call_id="call-1"), synthetic_reminder, second_ai_message]

    with acting_as(USER_A, ORG_S):
        result = await _deliberate_impl("plan it again", runtime=_runtime(messages=messages, tool_call_id="call-2"), app_config=_config())
    assert result == {"error": "Deliberation is limited to 1 call(s) per turn."}


@pytest.mark.asyncio
async def test_parallel_calls_in_one_ai_message_are_not_both_refused(org_world, _stub_fusion_panel):  # noqa: F811
    """Review finding: two parallel ``deliberate`` calls dispatched from the same
    AIMessage must not both see "1 already completed" and both refuse under a
    cap of 1 -- only the later one (by list position) should."""
    parallel_ai_message = AIMessage(content="", tool_calls=[{"name": "deliberate", "args": {}, "id": "call-1"}, {"name": "deliberate", "args": {}, "id": "call-2"}])
    messages = [HumanMessage(content="plan two things at once"), parallel_ai_message]

    with acting_as(USER_A, ORG_S):
        first = await _deliberate_impl("plan the first thing", runtime=_runtime(messages=messages, tool_call_id="call-1"), app_config=_config())
        second = await _deliberate_impl("plan the second thing", runtime=_runtime(messages=messages, tool_call_id="call-2"), app_config=_config())
    assert "error" not in first
    assert second == {"error": "Deliberation is limited to 1 call(s) per turn."}


# --- client-data check fails closed when the database is unavailable ---


@pytest.mark.asyncio
async def test_client_data_check_fails_closed_with_no_database(org_world, monkeypatch):  # noqa: F811
    monkeypatch.setattr("deerflow.persistence.engine.get_session_factory", lambda: None)
    with acting_as(USER_A, ORG_S):
        result = await _deliberate_impl("plan it", runtime=_runtime(project_id="proj-1"), app_config=_config())
    assert "error" in result
    assert "client data" in result["error"]


@pytest.mark.asyncio
async def test_no_pinned_project_is_not_treated_as_client_data(org_world, _stub_fusion_panel):  # noqa: F811
    with acting_as(USER_A, ORG_S):
        result = await _deliberate_impl("plan it", runtime=_runtime(), app_config=_config())
    assert "error" not in result


# --- the panel actually fans out to every model before the analyst runs ---


@pytest.mark.asyncio
async def test_run_fusion_panel_fans_out_to_every_panelist_then_synthesizes(monkeypatch):
    calls: list[tuple[str, str, str | None]] = []

    async def fake_call_model(prompt, *, model, api_key, system=None):
        calls.append((prompt, model, system))
        if model == "analyst-model":
            return '{"consensus":"agree on X","contradictions":"disagree on Y","unique_insights":"Z","blind_spots":"W"}'
        return f"{model}'s take on: {prompt}"

    monkeypatch.setattr("deerflow.tools.deliberate_tools._call_model", fake_call_model)

    result = await run_fusion_panel("plan the migration", panel_models=["panelist-a", "panelist-b"], analyst_model="analyst-model", api_key="test-key")

    assert result == {"consensus": "agree on X", "contradictions": "disagree on Y", "unique_insights": "Z", "blind_spots": "W"}
    panelist_calls = [c for c in calls if c[1] != "analyst-model"]
    assert {c[1] for c in panelist_calls} == {"panelist-a", "panelist-b"}
    assert all(c[0] == "plan the migration" for c in panelist_calls)
    analyst_call = next(c for c in calls if c[1] == "analyst-model")
    assert "panelist-a's take on: plan the migration" in analyst_call[0]
    assert "panelist-b's take on: plan the migration" in analyst_call[0]
    assert analyst_call[2] is not None  # the analyst gets its own system instructions


@pytest.mark.asyncio
async def test_run_fusion_panel_falls_back_on_an_unparseable_analyst_response(monkeypatch):
    async def fake_call_model(prompt, *, model, api_key, system=None):
        return "not json"

    monkeypatch.setattr("deerflow.tools.deliberate_tools._call_model", fake_call_model)

    result = await run_fusion_panel("plan it", panel_models=["panelist-a"], analyst_model="analyst-model", api_key="test-key")
    assert result["fallback"] is True
    assert result["consensus"] == "not json"
