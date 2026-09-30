"""Tests for the fleet-agent ``deliberate`` tool (queue item e13, OpenRouter Fusion panel).

Covers the accept bar named in QUEUE.md: the Momentum-staff-only gate, the
client-data refusal (and its verified-owner override), the budget cap (a
paused seat, per queue item e10), and one call per conversational turn. Pure
authorization/budget logic is covered by ``test_deliberate_workflow.py``;
this file is the tool layer that resolves the facts those checks need and
calls the (monkeypatched) panel.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from org_isolation_fixtures import ORG_S, USER_A, USER_C, acting_as, org_world  # noqa: F401

from deerflow.config.deliberate_config import DeliberateConfig
from deerflow.persistence.exec_seats import AgentSeatRepository
from deerflow.persistence.organizations.model import OrganizationMemberRow
from deerflow.persistence.projects.model import ProjectRow
from deerflow.persistence.user.model import UserRow
from deerflow.runtime.context_keys import PROJECT_CONTEXT_KEY
from deerflow.tools.deliberate_tools import _deliberate_impl

USER_D = "user-d"


async def _add_plain_member(session_factory, user_id: str, organization_id: str) -> None:
    """Seed a member (neither owner nor admin) of *organization_id* for this test only.

    Mirrors ``test_exec_seat_tools.py``'s helper of the same name.
    """
    now = datetime.now(UTC)
    async with session_factory() as session, session.begin():
        session.add(UserRow(id=user_id, email=f"{user_id}@example.com", password_hash=None, system_role="user", needs_setup=False, token_version=0, created_at=now))
        session.add(OrganizationMemberRow(organization_id=organization_id, user_id=user_id, role="member", status="active", created_at=now, updated_at=now))


class _DummyRuntime(SimpleNamespace):
    context: dict
    state: dict | None


def _runtime(*, momentum_staff: bool = True, agent_name: str | None = None, project_id: str | None = None, messages: list | None = None) -> _DummyRuntime:
    context: dict = {"momentum_staff": momentum_staff}
    if agent_name is not None:
        context["agent_name"] = agent_name
    if project_id is not None:
        context[PROJECT_CONTEXT_KEY] = {"project_id": project_id, "name": "", "instructions": ""}
    return _DummyRuntime(context=context, state={"messages": messages or []})


def _config(**overrides) -> SimpleNamespace:
    return SimpleNamespace(deliberate=DeliberateConfig(enabled=True, openrouter_api_key="test-key", **overrides))


async def _add_project(session_factory, *, project_id: str, user_id: str, client_id: str | None) -> None:
    async with session_factory() as session, session.begin():
        session.add(ProjectRow(id=project_id, user_id=user_id, client_id=client_id, name="p", instructions=""))


@pytest.fixture(autouse=True)
def _stub_fusion_panel(monkeypatch):
    async def fake_run_fusion_panel(prompt, *, model, api_key):
        fake_run_fusion_panel.calls.append((prompt, model, api_key))
        return {"consensus": "c", "contradictions": "", "unique_insights": "", "blind_spots": ""}

    fake_run_fusion_panel.calls = []
    monkeypatch.setattr("deerflow.tools.deliberate_tools.run_fusion_panel", fake_run_fusion_panel)
    return fake_run_fusion_panel


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
    assert _stub_fusion_panel.calls == [("plan it", "openrouter/auto", "test-key")]


@pytest.mark.asyncio
async def test_client_data_thread_refuses_without_override(org_world):  # noqa: F811
    session_factory = org_world
    await _add_project(session_factory, project_id="proj-1", user_id=USER_A, client_id="client-1")
    with acting_as(USER_A, ORG_S):
        result = await _deliberate_impl("plan it", runtime=_runtime(project_id="proj-1"), app_config=_config())
    assert result == {"error": ("This thread carries client data. The deliberation panel sends the prompt to several outside providers, outside MomoBot's Luna-only private-data lane, so an organization owner must override to run it here.")}


@pytest.mark.asyncio
async def test_client_data_thread_allowed_with_verified_owner_override(org_world, _stub_fusion_panel):  # noqa: F811
    session_factory = org_world
    await _add_project(session_factory, project_id="proj-1", user_id=USER_A, client_id="client-1")
    with acting_as(USER_A, ORG_S):  # USER_A is ORG_S's owner
        result = await _deliberate_impl("plan it", runtime=_runtime(project_id="proj-1"), override_client_data_refusal=True, app_config=_config())
    assert "error" not in result
    assert _stub_fusion_panel.calls


@pytest.mark.asyncio
async def test_client_data_override_ignored_for_a_plain_member(org_world):  # noqa: F811
    session_factory = org_world
    await _add_project(session_factory, project_id="proj-1", user_id=USER_A, client_id="client-1")
    await _add_plain_member(session_factory, USER_D, ORG_S)
    with acting_as(USER_D, ORG_S):
        result = await _deliberate_impl("plan it", runtime=_runtime(project_id="proj-1"), override_client_data_refusal=True, app_config=_config())
    assert "error" in result


@pytest.mark.asyncio
async def test_admin_can_also_override(org_world, _stub_fusion_panel):  # noqa: F811
    session_factory = org_world
    await _add_project(session_factory, project_id="proj-1", user_id=USER_A, client_id="client-1")
    with acting_as(USER_C, ORG_S):  # USER_C is ORG_S's admin, not just the owner
        result = await _deliberate_impl("plan it", runtime=_runtime(project_id="proj-1"), override_client_data_refusal=True, app_config=_config())
    assert "error" not in result


@pytest.mark.asyncio
async def test_paused_seat_refuses_the_call(org_world):  # noqa: F811
    session_factory = org_world
    with acting_as(USER_A, ORG_S):
        repo = AgentSeatRepository(session_factory)
        seat = await repo.claim_seat(seat="CMO", agent_name="cmo-agent", weekly_token_budget=100)
        await repo.set_paused(seat["id"], paused=True)

        result = await _deliberate_impl("plan it", runtime=_runtime(agent_name="cmo-agent"), app_config=_config())
    assert result == {"error": "This seat is over its weekly token budget; deliberation is paused until it resets."}


@pytest.mark.asyncio
async def test_second_call_in_the_same_turn_is_refused(org_world, _stub_fusion_panel):  # noqa: F811
    prior_ai_message = AIMessage(content="", tool_calls=[{"name": "deliberate", "args": {}, "id": "call-1"}])
    second_ai_message = AIMessage(content="", tool_calls=[{"name": "deliberate", "args": {}, "id": "call-2"}])
    messages = [HumanMessage(content="plan the big migration"), prior_ai_message, ToolMessage(content="ok", tool_call_id="call-1"), second_ai_message]

    with acting_as(USER_A, ORG_S):
        result = await _deliberate_impl("plan it again", runtime=_runtime(messages=messages), app_config=_config())
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
        result = await _deliberate_impl("plan the next one", runtime=_runtime(messages=messages), app_config=_config())
    assert "error" not in result
