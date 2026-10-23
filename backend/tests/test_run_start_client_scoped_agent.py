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

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from org_isolation_fixtures import ORG_B, ORG_S, STORAGE_S, USER_A, USER_B, USER_C, acting_as, org_world  # noqa: F401

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
BOUND_REGISTRY_ID = "bound-customer-registry"


@contextmanager
def _client_actor(actor: str = USER_B, *, system_role: str = "client", organization_role: str = "client"):
    from deerflow.runtime.user_context import WorkspaceStorageContext, get_storage_context, reset_current_user, reset_storage_context, set_current_user, set_storage_context

    with acting_as(actor, ORG_B):
        current = get_storage_context()
        storage_token = set_storage_context(WorkspaceStorageContext(actor_user_id=actor, organization_id=ORG_B, storage_user_id=current.storage_user_id, role=organization_role))
        token = set_current_user(SimpleNamespace(id=actor, system_role=system_role))
        try:
            yield
        finally:
            reset_current_user(token)
            reset_storage_context(storage_token)


async def _seed_bound_customer(session_factory):
    from sqlalchemy import update

    from deerflow.persistence.clients.model import ClientAssignmentRow
    from deerflow.persistence.organizations.model import OrganizationMemberRow, OrganizationRow
    from deerflow.persistence.user.model import UserRow

    client_repo = ClientRepository(session_factory)
    with acting_as(USER_A, ORG_S):
        client = await client_repo.create(display_name="Bound Synthetic Client", registry_id=BOUND_REGISTRY_ID)
    async with session_factory() as session, session.begin():
        await session.execute(update(OrganizationRow).where(OrganizationRow.id == ORG_B).values(customer_client_id=client["id"]))
        await session.execute(update(OrganizationMemberRow).where(OrganizationMemberRow.organization_id == ORG_B, OrganizationMemberRow.user_id == USER_B).values(role="client"))
        await session.execute(update(UserRow).where(UserRow.id == USER_B).values(system_role="client"))
        session.add_all(
            [
                ClientAssignmentRow(client_id=client["id"], user_id=USER_B, organization_id=ORG_B, role="client_contact"),
                OrganizationMemberRow(organization_id=ORG_B, user_id=USER_C, role="member", status="active"),
                ClientAssignmentRow(client_id=client["id"], user_id=USER_C, organization_id=ORG_S, role="account_manager"),
            ]
        )
    return client


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
    # Client-contact chats are creator-scoped, so the actor creates its own thread.
    with acting_as(actor, ORG_S):
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
        # The dedicated-workspace gate has its own suite (test_client_portal);
        # these cases exercise agent scoping behind it.
        patch("app.gateway.client_workspace.require_client_workspace", new=AsyncMock()),
    ):
        try:
            record = await start_run(body, thread_id, request)
        except HTTPException as exc:
            return exc
        await record.task
        return record


async def _start_bound_client(
    body: SimpleNamespace,
    thread_id: str,
    *,
    actor: str = USER_B,
    system_role: str = "client",
    organization_role: str = "client",
    runtime_agents: list[str] | None = None,
    runtime_contexts: list[dict] | None = None,
):
    thread_store = MemoryThreadMetaStore(InMemoryStore())
    with _client_actor(actor, system_role=system_role, organization_role=organization_role):
        await thread_store.create(thread_id, user_id=USER_B, metadata={})
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
            user=SimpleNamespace(id=actor, system_role=system_role),
            actor_user_id=actor,
            storage_user_id=USER_B,
            organization_id=ORG_B,
            organization_role=organization_role,
        ),
        app=SimpleNamespace(state=state),
    )

    async def fake_run_agent(*_args, **_kwargs):
        if runtime_agents is not None:
            runtime_agents.append(_kwargs["config"].get("context", {}).get("agent_name"))
        if runtime_contexts is not None:
            runtime_contexts.append(dict(_kwargs["config"].get("context", {})))
        return None

    with (
        _client_actor(actor, system_role=system_role, organization_role=organization_role),
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
async def test_assigned_member_can_start_agent_tagged_with_own_registry_id(stamped_agents) -> None:
    client_repo = ClientRepository(stamped_agents)
    with acting_as(USER_A, ORG_S):
        client = await client_repo.create(display_name="Registry Client", registry_id="registry-client-1")
        await client_repo.add_assignment(client["id"], USER_D, "client_contact")
        get_agent_store().create(
            "registry-agent",
            {"name": "registry-agent", "description": "registry tagged", "client_id": client["registry_id"]},
            "registry client soul",
            user_id=STORAGE_S,
        )

    result = await _start(USER_D, _body(assistant_id="registry-agent"), "thread-registry-own")
    assert not isinstance(result, HTTPException), result


@pytest.mark.asyncio
async def test_bound_customer_contact_can_start_row_and_registry_tagged_agents(stamped_agents) -> None:
    client = await _seed_bound_customer(stamped_agents)
    set_app_config(
        AppConfig.model_validate(
            {
                "sandbox": {"use": "deerflow.community.aio_sandbox:AioSandboxProvider", "network": {"mode": "isolated"}},
                "models": [{"name": "claude-opus-5-5", "use": "langchain_openai:ChatOpenAI", "model": "claude-opus-5-5"}],
                "momobot_max": {"enabled": True, "clients": [client["id"], client["registry_id"]]},
            }
        )
    )
    with _client_actor():
        store = get_agent_store()
        for name, tag in (("bound-row-agent", client["id"]), ("bound-registry-agent", client["registry_id"])):
            store.create(name, {"name": name, "description": "bound customer agent", "client_id": tag}, "bound client soul", user_id=USER_B)

    for name in ("bound-row-agent", "bound-registry-agent"):
        runtime_contexts: list[dict] = []
        result = await _start_bound_client(_body(assistant_id=name), f"thread-{name}", runtime_contexts=runtime_contexts)
        assert not isinstance(result, HTTPException), result
        assert runtime_contexts[0]["client_workspace_ceiling"] is True
        assert runtime_contexts[0]["momobot_tier"] == "max"
        assert runtime_contexts[0]["model_name"] == "claude-opus-5-5"


@pytest.mark.asyncio
async def test_bound_customer_account_manager_member_does_not_gain_agent_run_access(stamped_agents) -> None:
    client = await _seed_bound_customer(stamped_agents)
    set_app_config(
        AppConfig.model_validate(
            {
                "sandbox": {"use": "deerflow.community.aio_sandbox:AioSandboxProvider", "network": {"mode": "isolated"}},
                "models": [{"name": "claude-opus-5-5", "use": "langchain_openai:ChatOpenAI", "model": "claude-opus-5-5"}],
                "momobot_max": {"enabled": True, "clients": [client["id"], client["registry_id"]]},
            }
        )
    )
    with _client_actor():
        get_agent_store().create("bound-row-agent", {"name": "bound-row-agent", "description": "bound customer agent", "client_id": client["id"]}, "soul", user_id=USER_B)

    result = await _start_bound_client(
        _body(assistant_id="bound-row-agent"),
        "thread-account-manager",
        actor=USER_C,
        system_role="user",
        organization_role="member",
    )
    assert isinstance(result, HTTPException)
    assert (result.status_code, result.detail) == (422, MISSING_DETAIL)


@pytest.mark.asyncio
async def test_bound_customer_run_rejects_unassigned_tags_and_foreign_bucket(stamped_agents) -> None:
    client = await _seed_bound_customer(stamped_agents)
    client_repo = ClientRepository(stamped_agents)
    with acting_as(USER_A, ORG_S):
        other = await client_repo.create(display_name="Other Bound Client", registry_id="other-bound-registry")
    set_app_config(
        AppConfig.model_validate(
            {
                "sandbox": {"use": "deerflow.community.aio_sandbox:AioSandboxProvider", "network": {"mode": "isolated"}},
                "models": [{"name": "claude-opus-5-5", "use": "langchain_openai:ChatOpenAI", "model": "claude-opus-5-5"}],
                "momobot_max": {"enabled": True, "clients": [client["id"], client["registry_id"]]},
            }
        )
    )
    with _client_actor():
        store = get_agent_store()
        store.create("other-bound-agent", {"name": "other-bound-agent", "description": "unassigned other client", "client_id": other["registry_id"]}, "other client soul", user_id=USER_B)
        store.create("foreign-bucket-agent", {"name": "foreign-bucket-agent", "description": "foreign bucket", "client_id": client["id"]}, "foreign bucket soul", user_id="another-customer-storage")

    # Existing CLIENT policy falls back to MomoBot Max; neither tagged custom agent executes.
    for name in ("other-bound-agent", "foreign-bucket-agent"):
        runtime_agents: list[str] = []
        result = await _start_bound_client(_body(assistant_id=name), f"thread-{name}", runtime_agents=runtime_agents)
        assert not isinstance(result, HTTPException), result
        assert runtime_agents == ["momobot-max"]


@pytest.mark.asyncio
async def test_bound_customer_run_rejects_ambiguous_row_id_but_accepts_unique_registry_id(stamped_agents) -> None:
    client = await _seed_bound_customer(stamped_agents)
    client_repo = ClientRepository(stamped_agents)
    with acting_as(USER_A, ORG_S):
        await client_repo.create(display_name="Registry Collision", registry_id=client["id"])
    set_app_config(
        AppConfig.model_validate(
            {
                "sandbox": {"use": "deerflow.community.aio_sandbox:AioSandboxProvider", "network": {"mode": "isolated"}},
                "models": [{"name": "claude-opus-5-5", "use": "langchain_openai:ChatOpenAI", "model": "claude-opus-5-5"}],
                "momobot_max": {"enabled": True, "clients": [client["id"], client["registry_id"]]},
            }
        )
    )
    with _client_actor():
        store = get_agent_store()
        store.create("bound-row-agent", {"name": "bound-row-agent", "description": "ambiguous row tag", "client_id": client["id"]}, "soul", user_id=USER_B)
        store.create("bound-registry-agent", {"name": "bound-registry-agent", "description": "unique registry tag", "client_id": client["registry_id"]}, "soul", user_id=USER_B)

    denied = await _start_bound_client(_body(assistant_id="bound-row-agent"), "thread-bound-row-collision")
    assert isinstance(denied, HTTPException)
    assert (denied.status_code, denied.detail) == (422, MISSING_DETAIL)
    allowed = await _start_bound_client(_body(assistant_id="bound-registry-agent"), "thread-bound-registry-collision")
    assert not isinstance(allowed, HTTPException), allowed


@pytest.mark.asyncio
async def test_foreign_organization_registry_tag_cannot_start_agent(stamped_agents) -> None:
    client_repo = ClientRepository(stamped_agents)
    with acting_as(USER_B, ORG_B):
        foreign_client = await client_repo.create(display_name="Foreign Registry Client", registry_id="foreign-registry-only")
    with acting_as(USER_A, ORG_S):
        get_agent_store().create(
            "foreign-registry-agent",
            {"name": "foreign-registry-agent", "description": "foreign registry tagged", "client_id": foreign_client["registry_id"]},
            "foreign client soul",
            user_id=STORAGE_S,
        )

    result = await _start(USER_D, _body(assistant_id="foreign-registry-agent"), "thread-registry-foreign-org")
    assert isinstance(result, HTTPException)
    assert (result.status_code, result.detail) == (422, MISSING_DETAIL)


@pytest.mark.asyncio
async def test_client_row_registry_collision_cannot_start_agent_even_when_assigned(stamped_agents) -> None:
    client_repo = ClientRepository(stamped_agents)
    with acting_as(USER_A, ORG_S):
        assigned = await client_repo.create(display_name="Assigned Client")
        await client_repo.add_assignment(assigned["id"], USER_D, "client_contact")
        await client_repo.create(display_name="Registry Collision", registry_id=assigned["id"])
        get_agent_store().create(
            "collision-agent",
            {"name": "collision-agent", "description": "ambiguous client tag", "client_id": assigned["id"]},
            "assigned client soul",
            user_id=STORAGE_S,
        )

    result = await _start(USER_D, _body(assistant_id="collision-agent"), "thread-registry-collision")
    assert isinstance(result, HTTPException)
    assert (result.status_code, result.detail) == (422, MISSING_DETAIL)


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


@pytest.mark.asyncio
async def test_a_scalar_agent_name_refuses_with_422_instead_of_crashing(stamped_agents) -> None:
    """f102(d): ``configurable``/``context`` are untyped dicts, so a client can
    send ``agent_name: 42`` (or any non-string JSON scalar). ``str.strip()``
    on that value must not surface as an unhandled 500 — it can never name a
    real agent, so it gets the same 422 a missing/foreign agent gets."""
    await _seed(stamped_agents)

    scalar_bodies = {
        "configurable.agent_name": _body(config={"configurable": {"agent_name": 42}}),
        "context.agent_name": _body(config={"context": {"agent_name": 42}}),
        "context.agent_name-bool": _body(config={"context": {"agent_name": True}}),
        "context.agent_name-list": _body(config={"context": {"agent_name": ["c1-agent"]}}),
    }
    for label, body in scalar_bodies.items():
        result = await _start(USER_D, body, f"thread-scalar-{label.replace('.', '-')}")
        assert isinstance(result, HTTPException), (label, result)
        assert (result.status_code, result.detail) == (422, MISSING_DETAIL), label
