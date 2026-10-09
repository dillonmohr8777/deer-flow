"""Tests for enforcing a paused agent seat's weekly token budget (queue item f95).

``deerflow.exec_seats.budget.evaluate_all_seat_budgets`` (e10) already knows how
to pause and resume a seat, but nothing ever called it on a schedule and a
paused seat's agent could still run -- the pause had no effect. This file
covers the three gaps the finding named:

1. ``AgentSeatRepository.paused_seat_for_agent`` finds the blocking seat,
   matching case- and underscore/hyphen-insensitively.
2. ``start_run`` refuses a run naming a paused seat's agent.
3. The Gateway lifespan registers a recurring sweep when configured, and
   never does by default (or against an unconfigured test double).

A fourth gap, left open by this file's first pass (PR #85): a run naming its
agent only through ``context.agent_name`` never moved the needle on that
agent's seat burn, since ``token_burn_since`` only ever matched
``RunRow.assistant_id`` (which stays the default lead agent in that case).
``start_run`` now stamps the resolved effective agent name onto every run's
metadata; see ``test_start_run_stamps_the_effective_agent_name_on_every_run``
below and ``test_context_agent_name_run_counts_toward_seat_burn_with_default_assistant_id``
in ``test_agent_seat_budget.py`` for the burn-accounting half.
"""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from org_isolation_fixtures import ORG_A, ORG_B, USER_A, acting_as, org_world  # noqa: F401

from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config
from deerflow.persistence.exec_seats import AgentSeatRepository, AgentSeatStatus
from deerflow.runtime.user_context import WorkspaceStorageContext, reset_storage_context, set_storage_context

CMO_SEAT = "CMO"


@contextmanager
def _acting_with_no_organization(actor: str):
    """Internal / auth-disabled / IM-channel shape: a real actor, no org at all.

    Mirrors ``test_exec_seat_tools.py``'s helper of the same name (f72);
    ``acting_as(actor, None)`` cannot express this since it falls back to
    the actor's own private organization when given ``None``.
    """
    token = set_storage_context(WorkspaceStorageContext(actor_user_id=actor, organization_id=None, storage_user_id=actor, role=None))
    try:
        yield
    finally:
        reset_storage_context(token)


@pytest.fixture
def _stub_app_config():
    """Keep start_run reachable without a developer-local config.yaml (mirrors test_gateway_services.py)."""
    set_app_config(AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}}))
    yield
    reset_app_config()


async def _ratify(repo: AgentSeatRepository, *, seat: str, agent_name: str, weekly_token_budget: int = 1000) -> dict:
    claimed = await repo.claim_seat(seat=seat, agent_name=agent_name, weekly_token_budget=weekly_token_budget, claimed_by_user_id=USER_A)
    return await repo.patch_seat(claimed["id"], status=AgentSeatStatus.RATIFIED, ratified_by_user_id=USER_A)


@pytest.mark.asyncio
async def test_paused_seat_for_agent_finds_an_exact_match(org_world):  # noqa: F811
    repo = AgentSeatRepository(org_world)
    with acting_as(USER_A, ORG_A):
        seat = await _ratify(repo, seat=CMO_SEAT, agent_name="cmo-agent")
        await repo.set_paused(seat["id"], paused=True)

        found = await repo.paused_seat_for_agent("cmo-agent")

    assert found is not None
    assert found["id"] == seat["id"]


@pytest.mark.asyncio
async def test_paused_seat_for_agent_matches_case_and_underscore_variants(org_world):  # noqa: F811
    """f95: a seat claimed unnormalized must still block the normalized name and vice versa."""
    repo = AgentSeatRepository(org_world)
    with acting_as(USER_A, ORG_A):
        seat = await _ratify(repo, seat=CMO_SEAT, agent_name="CMO_Agent")
        await repo.set_paused(seat["id"], paused=True)

        found = await repo.paused_seat_for_agent("cmo-agent")

    assert found is not None
    assert found["id"] == seat["id"]


@pytest.mark.asyncio
async def test_paused_seat_for_agent_is_none_when_not_paused(org_world):  # noqa: F811
    repo = AgentSeatRepository(org_world)
    with acting_as(USER_A, ORG_A):
        await _ratify(repo, seat=CMO_SEAT, agent_name="cmo-agent")

        found = await repo.paused_seat_for_agent("cmo-agent")

    assert found is None


@pytest.mark.asyncio
async def test_paused_seat_for_agent_is_scoped_to_the_seats_own_organization(org_world):  # noqa: F811
    repo = AgentSeatRepository(org_world)
    with acting_as(USER_A, ORG_A):
        seat = await _ratify(repo, seat=CMO_SEAT, agent_name="cmo-agent")
        await repo.set_paused(seat["id"], paused=True)

    with acting_as(USER_A, ORG_B):
        # A same-named agent in a foreign org must never be visible here.
        found = await repo.paused_seat_for_agent("cmo-agent")

    assert found is None


@pytest.mark.asyncio
async def test_paused_seat_for_agent_is_none_with_no_resolved_organization(org_world):  # noqa: F811
    """f99: an internal/channel run with no org context must never fail open
    across every organization's paused seats. Before the fix, ``_scope``
    treated ``organization_id=None`` as "no filter" here too, so this would
    429 an unrelated org's run and leak the blocking seat's title."""
    repo = AgentSeatRepository(org_world)
    with acting_as(USER_A, ORG_A):
        seat = await _ratify(repo, seat=CMO_SEAT, agent_name="cmo-agent")
        await repo.set_paused(seat["id"], paused=True)

    with _acting_with_no_organization(USER_A):
        found = await repo.paused_seat_for_agent("cmo-agent")

    assert found is None


@pytest.mark.asyncio
async def test_paused_seat_blocking_is_none_with_no_resolved_organization(org_world):  # noqa: F811
    """The accept bar's own wording: a paused seat exists in ORG_A, and
    ``paused_seat_blocking`` (the public entry point ``_refuse_if_agent_seat_paused``
    actually calls) must return ``None`` -- never block, never leak the
    seat's title -- for a caller with no org at all."""
    from deerflow.exec_seats.budget import paused_seat_blocking

    repo = AgentSeatRepository(org_world)
    with acting_as(USER_A, ORG_A):
        seat = await _ratify(repo, seat=CMO_SEAT, agent_name="cmo-agent")
        await repo.set_paused(seat["id"], paused=True)

    with _acting_with_no_organization(USER_A):
        found = await paused_seat_blocking("cmo-agent")

    assert found is None


@pytest.mark.asyncio
async def test_paused_seat_blocking_still_blocks_a_seat_claimed_with_no_organization(org_world):  # noqa: F811
    """f123 (review of the f99 fix): a seat claimed with no active org (auth-disabled
    or an internal caller) is itself stored with ``organization_id=None`` --
    ``organization_for_write``'s quarantine marker, a real state, not one that never
    occurs. The f99 fix must not make every such seat's pause silently unenforceable
    just to stop a null-org caller from matching *another* organization's seat."""
    from deerflow.exec_seats.budget import paused_seat_blocking

    repo = AgentSeatRepository(org_world)
    with _acting_with_no_organization(USER_A):
        seat = await _ratify(repo, seat=CMO_SEAT, agent_name="cmo-agent")
        await repo.set_paused(seat["id"], paused=True)

        found = await repo.paused_seat_for_agent("cmo-agent")
        blocking = await paused_seat_blocking("cmo-agent")

    assert seat["organization_id"] is None
    assert found is not None
    assert found["id"] == seat["id"]
    assert blocking is not None
    assert blocking["id"] == seat["id"]


@pytest.mark.asyncio
async def test_paused_seat_for_agent_ignores_a_reopened_seat(org_world):  # noqa: F811
    """A paused-then-reopened seat is no longer claimed/ratified by anyone -- nothing to block."""
    repo = AgentSeatRepository(org_world)
    with acting_as(USER_A, ORG_A):
        seat = await _ratify(repo, seat=CMO_SEAT, agent_name="cmo-agent")
        await repo.set_paused(seat["id"], paused=True)
        await repo.patch_seat(seat["id"], status=AgentSeatStatus.REOPENED)

        found = await repo.paused_seat_for_agent("cmo-agent")

    assert found is None


# ---------------------------------------------------------------------------
# start_run refusal
# ---------------------------------------------------------------------------


def _start_run_request():
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.store.memory import InMemoryStore

    from deerflow.persistence.thread_meta.memory import MemoryThreadMetaStore
    from deerflow.runtime import RunManager
    from deerflow.runtime.events.store.memory import MemoryRunEventStore
    from deerflow.runtime.runs.store.memory import MemoryRunStore

    run_manager = RunManager(store=MemoryRunStore())
    state = SimpleNamespace(
        stream_bridge=SimpleNamespace(),
        run_manager=run_manager,
        checkpointer=InMemorySaver(),
        store=InMemoryStore(),
        run_event_store=MemoryRunEventStore(),
        run_events_config=None,
        thread_store=MemoryThreadMetaStore(InMemoryStore()),
    )
    return SimpleNamespace(
        headers={},
        state=SimpleNamespace(auth_source=None),
        app=SimpleNamespace(state=state),
    )


@pytest.mark.asyncio
async def test_start_run_refuses_a_paused_seats_agent(org_world, _stub_app_config):  # noqa: F811
    from fastapi import HTTPException

    from app.gateway.run_models import RunCreateRequest
    from app.gateway.services import start_run

    repo = AgentSeatRepository(org_world)
    with acting_as(USER_A, ORG_A):
        seat = await _ratify(repo, seat=CMO_SEAT, agent_name="cmo-agent")
        await repo.set_paused(seat["id"], paused=True)

        body = RunCreateRequest(assistant_id="lead_agent", context={"agent_name": "cmo-agent"}, input={"messages": [{"type": "human", "content": "hi"}]})
        request = _start_run_request()

        with pytest.raises(HTTPException) as exc_info:
            await start_run(body, "thread-seat-paused", request)

    assert exc_info.value.status_code == 429
    assert "CMO" in exc_info.value.detail


@pytest.mark.asyncio
async def test_start_run_allows_an_unpaused_seats_agent(org_world, _stub_app_config):  # noqa: F811
    from unittest.mock import patch

    from app.gateway.run_models import RunCreateRequest
    from app.gateway.services import start_run

    repo = AgentSeatRepository(org_world)
    with acting_as(USER_A, ORG_A):
        await _ratify(repo, seat=CMO_SEAT, agent_name="cmo-agent")

        body = RunCreateRequest(assistant_id="lead_agent", context={"agent_name": "cmo-agent"}, input={"messages": [{"type": "human", "content": "hi"}]})
        request = _start_run_request()

        async def fake_run_agent(*_args, **_kwargs):
            return None

        with (
            patch("app.gateway.services.resolve_agent_factory", return_value=object()),
            patch("app.gateway.services.run_agent", side_effect=fake_run_agent),
            patch("app.gateway.services._load_scope_agent_config", return_value=None),
        ):
            record = await start_run(body, "thread-seat-ok", request)
            await record.task

    assert record is not None


@pytest.mark.asyncio
async def test_start_run_does_not_refuse_the_default_agent_even_with_a_paused_seat(org_world, _stub_app_config):  # noqa: F811
    """No ``context.agent_name`` override means the default lead agent runs -- never a seat's own agent."""
    from unittest.mock import patch

    from app.gateway.run_models import RunCreateRequest
    from app.gateway.services import start_run

    repo = AgentSeatRepository(org_world)
    with acting_as(USER_A, ORG_A):
        seat = await _ratify(repo, seat=CMO_SEAT, agent_name="cmo-agent")
        await repo.set_paused(seat["id"], paused=True)

        body = RunCreateRequest(input={"messages": [{"type": "human", "content": "hi"}]})
        request = _start_run_request()

        async def fake_run_agent(*_args, **_kwargs):
            return None

        with (
            patch("app.gateway.services.resolve_agent_factory", return_value=object()),
            patch("app.gateway.services.run_agent", side_effect=fake_run_agent),
        ):
            record = await start_run(body, "thread-default-agent", request)
            await record.task

    assert record is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("scalar_agent_name", [42, 0, False, []], ids=["int", "zero", "false", "list"])
@pytest.mark.parametrize("container", ["context", "configurable"])
async def test_start_run_refuses_a_scalar_agent_name_with_422_instead_of_crashing(org_world, _stub_app_config, container, scalar_agent_name):  # noqa: F811
    """Review of f98/PR #85: ``configurable``/``context`` are untyped dicts, so a
    client can send ``agent_name: 42`` (or any non-string JSON scalar). Before
    this fix, ``scope_assistant_id.strip()`` -- both inside
    ``_refuse_if_agent_seat_paused`` -> ``paused_seat_for_agent`` and the
    ``effective_agent_name`` metadata stamp a few lines below it -- crashed
    with an unhandled ``AttributeError`` (a 500), earlier in ``start_run``
    than #90's own fix in ``_load_scope_agent_config`` ever runs. A non-string
    value can never name a real agent, so it must get the same 422 a
    missing/foreign agent already gets.

    f116 review: a *falsy* non-string (``0``, ``False``, ``[]``) must refuse
    the same way -- the raw value has to be checked before the
    ``or _DEFAULT_ASSISTANT_ID`` fallback, or it silently becomes the default
    agent and later crashes the worker with a ``ValueError`` instead."""
    from fastapi import HTTPException

    from app.gateway.run_models import RunCreateRequest
    from app.gateway.services import start_run

    with acting_as(USER_A, ORG_A):
        kwargs = {"context": {"agent_name": scalar_agent_name}} if container == "context" else {"config": {"configurable": {"agent_name": scalar_agent_name}}}
        body = RunCreateRequest(assistant_id="lead_agent", input={"messages": [{"type": "human", "content": "hi"}]}, **kwargs)
        request = _start_run_request()
        thread_id = f"thread-scalar-agent-name-{container}-{type(scalar_agent_name).__name__}"

        with pytest.raises(HTTPException) as exc_info:
            await start_run(body, thread_id, request)

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "knowledge_scope assistant configuration could not be resolved"


@pytest.mark.asyncio
async def test_start_run_treats_none_and_empty_string_agent_name_as_the_default(org_world, _stub_app_config):  # noqa: F811
    """``None``/``""`` are still the "no override" signal, not a refusal --
    only a genuinely non-string value refuses."""
    from unittest.mock import patch

    from app.gateway.run_models import RunCreateRequest
    from app.gateway.services import start_run

    with acting_as(USER_A, ORG_A):

        async def fake_run_agent(*_args, **_kwargs):
            return None

        with (
            patch("app.gateway.services.resolve_agent_factory", return_value=object()),
            patch("app.gateway.services.run_agent", side_effect=fake_run_agent),
        ):
            for label, value in (("none", None), ("empty", "")):
                body = RunCreateRequest(assistant_id="lead_agent", context={"agent_name": value}, input={"messages": [{"type": "human", "content": "hi"}]})
                request = _start_run_request()
                record = await start_run(body, f"thread-empty-agent-name-{label}", request)
                await record.task
                assert record is not None


# ---------------------------------------------------------------------------
# Effective-agent-name metadata stamp (burn-accounting gap left open by PR #85)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_run_stamps_the_effective_agent_name_on_every_run(org_world, _stub_app_config):  # noqa: F811
    """``token_burn_since`` needs this even when ``assistant_id`` stays the default."""
    from unittest.mock import patch

    from app.gateway.run_models import RunCreateRequest
    from app.gateway.services import start_run
    from deerflow.persistence.exec_seats import EFFECTIVE_AGENT_NAME_METADATA_KEY

    repo = AgentSeatRepository(org_world)
    with acting_as(USER_A, ORG_A):
        await _ratify(repo, seat=CMO_SEAT, agent_name="cmo-agent")

        body = RunCreateRequest(assistant_id="lead_agent", context={"agent_name": "cmo-agent"}, input={"messages": [{"type": "human", "content": "hi"}]})
        request = _start_run_request()

        async def fake_run_agent(*_args, **_kwargs):
            return None

        with (
            patch("app.gateway.services.resolve_agent_factory", return_value=object()),
            patch("app.gateway.services.run_agent", side_effect=fake_run_agent),
            patch("app.gateway.services._load_scope_agent_config", return_value=None),
        ):
            record = await start_run(body, "thread-effective-name-stamp", request)
            await record.task

    assert record.metadata[EFFECTIVE_AGENT_NAME_METADATA_KEY] == "cmo-agent"


@pytest.mark.asyncio
async def test_start_run_stamps_a_normalized_effective_agent_name(org_world, _stub_app_config):  # noqa: F811
    """f97 review: an un-normalized ``context.agent_name`` (e.g. ``CMO-Agent``)
    must stamp the same normalized form ``paused_seat_for_agent`` already
    matches against, or ``token_burn_since`` never sees the run's spend."""
    from unittest.mock import patch

    from app.gateway.run_models import RunCreateRequest
    from app.gateway.services import start_run
    from deerflow.persistence.exec_seats import EFFECTIVE_AGENT_NAME_METADATA_KEY

    repo = AgentSeatRepository(org_world)
    with acting_as(USER_A, ORG_A):
        await _ratify(repo, seat=CMO_SEAT, agent_name="cmo-agent")

        body = RunCreateRequest(assistant_id="lead_agent", context={"agent_name": "CMO-Agent"}, input={"messages": [{"type": "human", "content": "hi"}]})
        request = _start_run_request()

        async def fake_run_agent(*_args, **_kwargs):
            return None

        with (
            patch("app.gateway.services.resolve_agent_factory", return_value=object()),
            patch("app.gateway.services.run_agent", side_effect=fake_run_agent),
            patch("app.gateway.services._load_scope_agent_config", return_value=None),
        ):
            record = await start_run(body, "thread-effective-name-case-variant", request)
            await record.task

    assert record.metadata[EFFECTIVE_AGENT_NAME_METADATA_KEY] == "cmo-agent"


@pytest.mark.asyncio
async def test_start_run_replaces_a_caller_forged_effective_agent_name(org_world, _stub_app_config):  # noqa: F811
    """A client cannot claim someone else's seat's burn for its own run.

    A default-agent run holds no seat, so the forged key is dropped rather than
    replaced (stamping ``lead-agent`` polluted ordinary run metadata).
    """
    from unittest.mock import patch

    from app.gateway.run_models import RunCreateRequest
    from app.gateway.services import start_run
    from deerflow.persistence.exec_seats import EFFECTIVE_AGENT_NAME_METADATA_KEY

    with acting_as(USER_A, ORG_A):
        body = RunCreateRequest(
            input={"messages": [{"type": "human", "content": "hi"}]},
            metadata={EFFECTIVE_AGENT_NAME_METADATA_KEY: "forged-cmo-agent"},
        )
        request = _start_run_request()

        async def fake_run_agent(*_args, **_kwargs):
            return None

        with (
            patch("app.gateway.services.resolve_agent_factory", return_value=object()),
            patch("app.gateway.services.run_agent", side_effect=fake_run_agent),
        ):
            record = await start_run(body, "thread-effective-name-forged", request)
            await record.task

    assert EFFECTIVE_AGENT_NAME_METADATA_KEY not in record.metadata


# ---------------------------------------------------------------------------
# Gateway lifespan registration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seat_budget_loop_starts_when_enabled():
    import asyncio

    from app.gateway.app import _start_seat_budget_loop
    from deerflow.config.exec_seats_config import ExecSeatsConfig

    startup_config = SimpleNamespace(exec_seats=ExecSeatsConfig(budget_check_enabled=True, budget_check_interval_seconds=60))
    task = _start_seat_budget_loop(startup_config)
    try:
        assert task is not None
        assert not task.done()
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_seat_budget_loop_does_not_start_by_default():
    from app.gateway.app import _start_seat_budget_loop
    from deerflow.config.exec_seats_config import ExecSeatsConfig

    assert _start_seat_budget_loop(SimpleNamespace(exec_seats=ExecSeatsConfig())) is None


def test_seat_budget_loop_does_not_start_against_an_unconfigured_test_double():
    """A bare SimpleNamespace/MagicMock startup_config (most existing lifespan tests) must never start it."""
    from unittest.mock import MagicMock

    from app.gateway.app import _start_seat_budget_loop

    assert _start_seat_budget_loop(SimpleNamespace()) is None
    assert _start_seat_budget_loop(MagicMock()) is None


@pytest.mark.asyncio
async def test_lifespan_registers_the_seat_budget_loop_when_enabled():
    import asyncio as _asyncio
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock, MagicMock, patch

    from fastapi import FastAPI

    from app.gateway.app import lifespan
    from deerflow.config.exec_seats_config import ExecSeatsConfig

    @asynccontextmanager
    async def _noop_langgraph_runtime(_app, _startup_config):
        yield

    app = FastAPI()
    startup_config = SimpleNamespace(
        log_level="INFO",
        memory=SimpleNamespace(enabled=False, shutdown_flush_timeout_seconds=5.0),
        exec_seats=ExecSeatsConfig(budget_check_enabled=True, budget_check_interval_seconds=3600),
    )
    fake_service = MagicMock()
    fake_service.get_status.return_value = {}

    async def fake_start(_startup_config, **_kwargs):
        return fake_service

    with (
        patch("app.gateway.app.get_app_config", return_value=startup_config),
        patch("app.gateway.app.get_gateway_config", return_value=MagicMock(host="x", port=0)),
        patch("app.gateway.app.langgraph_runtime", _noop_langgraph_runtime),
        patch("app.gateway.app.auth.close_oidc_service", AsyncMock()),
        patch("app.channels.service.start_channel_service", side_effect=fake_start),
        patch("app.channels.service.stop_channel_service", AsyncMock()),
        patch("deerflow.skills.projection.ensure_public_skill_projection"),
        patch("deerflow.agents.memory.get_memory_manager", return_value=MagicMock()),
    ):
        async with lifespan(app):
            task = app.state.seat_budget_loop_task
            assert task is not None
            assert not task.done()

        assert task.done()
        assert task.cancelled()

    await _asyncio.sleep(0)
