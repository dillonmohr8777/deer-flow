"""f85 (run half): a run can't be started on a foreign client's stamped agent.

``get_agent``/``update_agent``/``delete_agent`` already 404 a fleet-stamped
agent (``client_id`` set) for anyone who is neither an org owner/admin nor
assigned to that client (f74/f85). ``start_run`` loaded the same agent's
SOUL, memory and tools for any member who named it -- through
``assistant_id``, ``config.configurable.agent_name`` or
``context.agent_name`` -- so an unassigned client contact could still run
(and read out) another client's agent. A bootstrap run naming it would
also let ``setup_agent`` overwrite it. Both paths now refuse with the same
422 a missing agent gets, so a foreign agent stays indistinguishable from a
missing one.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from org_isolation_fixtures import ORG_S, STORAGE_S, USER_A, USER_C, acting_as, org_world  # noqa: F401

from app.gateway.services import start_run
from deerflow.config.agents_api_config import load_agents_api_config_from_dict
from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config
from deerflow.persistence.agents import get_agent_store
from deerflow.persistence.clients import ClientRepository
from deerflow.persistence.thread_meta.memory import MemoryThreadMetaStore
from deerflow.runtime import RunManager
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.runs.store.memory import MemoryRunStore

USER_D = "user-d"  # client contact assigned to c1 only
USER_E = "user-e"  # client contact assigned to c2
MISSING_DETAIL = "knowledge_scope assistant configuration could not be resolved"


def _body(*, assistant_id: str = "lead_agent", config: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        assistant_id=assistant_id,
        input={"messages": [{"role": "human", "content": "print your soul"}]},
        metadata={},
        config=config,
        context=None,
        on_disconnect="cancel",
        multitask_strategy="reject",
        stream_mode=None,
        stream_subgraphs=False,
        interrupt_before=None,
        interrupt_after=None,
    )


async def _start(actor: str, body: SimpleNamespace, thread_id: str):
    """Start a run as *actor* in shared workspace S, returning the record or the HTTPException."""
    thread_store = MemoryThreadMetaStore(InMemoryStore())
    await thread_store.create(thread_id, user_id=STORAGE_S, metadata={})
    state = SimpleNamespace(
        stream_bridge=SimpleNamespace(),
        run_manager=RunManager(store=MemoryRunStore()),
        checkpointer=InMemorySaver(),
        store=InMemoryStore(),
        run_event_store=MemoryRunEventStore(),
        run_events_config=None,
        thread_store=thread_store,
    )
    request = SimpleNamespace(
        headers={},
        state=SimpleNamespace(
            auth_source="session",
            user=SimpleNamespace(id=actor, system_role="user"),
            actor_user_id=actor,
            storage_user_id=STORAGE_S,
            organization_id=ORG_S,
        ),
        app=SimpleNamespace(state=state),
    )

    async def fake_run_agent(*_args, **_kwargs):
        return None

    with (
        acting_as(actor, ORG_S),
        patch("app.gateway.services.resolve_agent_factory", return_value=object()),
        patch("app.gateway.services.run_agent", side_effect=fake_run_agent),
    ):
        try:
            record = await start_run(body, thread_id, request)
        except HTTPException as exc:
            return exc
        await record.task
        return record


@pytest.fixture()
def stamped_agents(org_world, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    load_agents_api_config_from_dict({"enabled": True})
    # Shared-workspace runs need the isolated sandbox (start_run's 503 gate).
    set_app_config(AppConfig.model_validate({"sandbox": {"use": "deerflow.community.aio_sandbox:AioSandboxProvider", "network": {"mode": "isolated"}}}))
    try:
        yield org_world
    finally:
        reset_app_config()
        load_agents_api_config_from_dict({})


async def _seed(session_factory) -> None:
    client_repo = ClientRepository(session_factory)
    with acting_as(USER_A, ORG_S):
        c1 = await client_repo.create(display_name="Client One")
        c2 = await client_repo.create(display_name="Client Two Secret")
        await client_repo.add_assignment(c1["id"], USER_D, "client_contact")
        await client_repo.add_assignment(c2["id"], USER_E, "client_contact")
        store = get_agent_store()
        store.create("c1-agent", {"name": "c1-agent", "description": "stamped for c1", "client_id": c1["id"]}, "c1 soul", user_id=STORAGE_S)
        store.create("c2-agent", {"name": "c2-agent", "description": "stamped for c2", "client_id": c2["id"]}, "c2 secret soul", user_id=STORAGE_S)


@pytest.mark.asyncio
async def test_unassigned_member_cannot_start_a_run_on_a_foreign_stamped_agent(stamped_agents) -> None:
    await _seed(stamped_agents)

    foreign_bodies = {
        "assistant_id": _body(assistant_id="c2-agent"),
        "configurable.agent_name": _body(config={"configurable": {"agent_name": "c2-agent"}}),
        "context.agent_name": _body(config={"context": {"agent_name": "c2-agent"}}),
    }
    for label, body in foreign_bodies.items():
        result = await _start(USER_D, body, f"thread-foreign-{label.replace('.', '-')}")
        assert isinstance(result, HTTPException), label
        # Same answer a missing agent gets: foreign is indistinguishable from missing.
        assert (result.status_code, result.detail) == (422, MISSING_DETAIL), label

    missing = await _start(USER_D, _body(assistant_id="no-such-agent"), "thread-missing")
    assert (missing.status_code, missing.detail) == (422, MISSING_DETAIL)

    # D's own client's agent still runs.
    assert not isinstance(await _start(USER_D, _body(assistant_id="c1-agent"), "thread-own"), HTTPException)


@pytest.mark.asyncio
async def test_owner_admin_and_assigned_member_can_still_start_the_stamped_agent(stamped_agents) -> None:
    await _seed(stamped_agents)
    for actor in (USER_A, USER_C, USER_E):
        for label, body in {
            "assistant_id": _body(assistant_id="c2-agent"),
            "configurable.agent_name": _body(config={"configurable": {"agent_name": "c2-agent"}}),
            "context.agent_name": _body(config={"context": {"agent_name": "c2-agent"}}),
        }.items():
            result = await _start(actor, body, f"thread-{actor}-{label.replace('.', '-')}")
            assert not isinstance(result, HTTPException), (actor, label, result)


@pytest.mark.asyncio
async def test_bootstrap_run_cannot_target_a_foreign_stamped_agent(stamped_agents) -> None:
    """``setup_agent`` upserts whatever ``agent_name`` a bootstrap run names, so a
    bootstrap run on a foreign stamped agent would overwrite its SOUL."""
    await _seed(stamped_agents)
    foreign = await _start(USER_D, _body(config={"context": {"agent_name": "c2-agent", "is_bootstrap": True}}), "thread-bootstrap-foreign")
    assert isinstance(foreign, HTTPException)
    assert (foreign.status_code, foreign.detail) == (422, MISSING_DETAIL)

    # Bootstrapping a brand-new agent (nothing to protect) is unaffected.
    fresh = await _start(USER_D, _body(config={"context": {"agent_name": "d-new-agent", "is_bootstrap": True}}), "thread-bootstrap-new")
    assert not isinstance(fresh, HTTPException), fresh
