"""Real start_run admission against the effective agent model; no provider calls."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

from app.gateway import services
from app.gateway.run_models import RunCreateRequest
from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config
from deerflow.persistence.thread_meta.memory import MemoryThreadMetaStore
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.runs.manager import RunManager
from deerflow.runtime.runs.store.memory import MemoryRunStore
from deerflow.runtime.user_context import reset_current_user, set_current_user

EXPENSIVE = "claude-opus-5-5"
CHEAP = "cheap-model"
pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    yield
    reset_app_config()


def harness(monkeypatch, *, role="client", refusal=None, router_enabled=True, authorization=None, tier="max"):
    prices = {CHEAP: {"input_per_mtok": 1, "output_per_mtok": 1}, EXPENSIVE: {"input_per_mtok": 10, "output_per_mtok": 10}}
    if refusal == "unpriced":
        prices.pop(EXPENSIVE)
    if refusal == "unpriced-base":
        prices.pop(CHEAP)
    config = AppConfig.model_validate(
        {
            "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
            "models": [{"name": name, "model": name, "use": "langchain_openai:ChatOpenAI"} for name in (EXPENSIVE, CHEAP)],
            "momobot_max": {"enabled": True, "model": EXPENSIVE, "clients": ["cost-client"], "base_model": CHEAP},
            **({"authorization": authorization} if authorization is not None else {}),
            "cost_router": {
                "enabled": router_enabled,
                "default_route": "bulk",
                "routes": {"bulk": {"model": CHEAP, "daily_cap_usd": 1}, "max": {"model": EXPENSIVE, "daily_cap_usd": 0.1}},
                "prices": prices,
                **({"denylist": [EXPENSIVE]} if refusal == "denied" else {}),
            },
        }
    )
    set_app_config(config)
    store = MemoryRunStore()
    manager = RunManager(store=store)
    manager.create_or_reject = AsyncMock(wraps=manager.create_or_reject)
    threads = MemoryThreadMetaStore(InMemoryStore())
    threads.create = AsyncMock(wraps=threads.create)
    user = SimpleNamespace(id="cost-test-user", system_role=role, oauth_provider=None, oauth_id=None)
    request = SimpleNamespace(
        headers={},
        state=SimpleNamespace(auth_source=None, user=user),
        app=SimpleNamespace(
            state=SimpleNamespace(
                stream_bridge=SimpleNamespace(), run_manager=manager, run_store=store, checkpointer=InMemorySaver(), store=InMemoryStore(), run_event_store=MemoryRunEventStore(), run_events_config=None, thread_store=threads
            )
        ),
    )
    worker = AsyncMock()
    seed = AsyncMock()
    monkeypatch.setattr(services, "resolve_agent_factory", lambda _: object())
    monkeypatch.setattr(services, "run_agent", worker)
    monkeypatch.setattr(services, "ensure_checkpoint_history_seeded", seed)
    monkeypatch.setattr(services, "_refuse_if_agent_seat_paused", AsyncMock())
    # Dedicated workspace authorization has its own SQL/AuthMiddleware suite.
    # This fixture starts after that gate, solely to exercise cost admission.
    monkeypatch.setattr("app.gateway.client_workspace.require_client_workspace", AsyncMock())
    monkeypatch.setattr("app.gateway.momobot_max.client_keys_for_user", AsyncMock(return_value=("cost-client",) if tier == "max" else ()))
    return SimpleNamespace(config=config, store=store, manager=manager, threads=threads, request=request, user=user, worker=worker, seed=seed)


async def launch(h, context, *, config=None):
    token = set_current_user(h.user)
    try:
        body = RunCreateRequest(input={"messages": [{"role": "user", "content": "Synthetic request"}]}, context=context, config=config)
        record = await services.start_run(body, "cost-thread", h.request)
        await record.task
        return record
    finally:
        reset_current_user(token)


@pytest.mark.parametrize(("refusal", "status"), [("over-cap", 429), ("unpriced", 402), ("denied", 403)])
async def test_client_max_refuses_its_real_model_before_any_run_or_checkpoint(monkeypatch, refusal, status):
    h = harness(monkeypatch, refusal=refusal)
    if refusal == "over-cap":
        await h.store.put("prior-max", thread_id="prior-thread", model_name=EXPENSIVE)
        await h.store.update_run_completion(
            "prior-max", status="success", total_input_tokens=20000, total_output_tokens=0, total_tokens=20000, token_usage_by_model={EXPENSIVE: {"input_tokens": 20000, "output_tokens": 0, "total_tokens": 20000}}
        )
    before = dict(h.store._runs)
    with pytest.raises(HTTPException) as error:
        await launch(h, {"agent_name": "finance-bot", "model_name": CHEAP, "task_class": "bulk"}, config={"configurable": {"model": CHEAP}})
    assert error.value.status_code == status
    assert EXPENSIVE in error.value.detail or "max" in error.value.detail
    h.manager.create_or_reject.assert_not_awaited()
    h.threads.create.assert_not_awaited()
    h.seed.assert_not_awaited()
    h.worker.assert_not_awaited()
    assert h.store._runs == before


async def test_client_max_scrubs_overrides_then_pins_and_records_the_admitted_model(monkeypatch):
    h = harness(monkeypatch)
    record = await launch(h, {"agent_name": "finance-bot", "model_name": "unknown-client-override", "model": CHEAP}, config={"configurable": {"model_name": CHEAP}})
    actual = h.worker.await_args.kwargs["config"]
    for section in ("configurable", "context"):
        assert actual[section]["agent_name"] == "momobot-max"
        assert actual[section]["model_name"] == EXPENSIVE
        assert "model" not in actual[section]
    assert (await h.store.get(record.run_id))["model_name"] == EXPENSIVE


@pytest.mark.parametrize(
    ("context", "router_enabled", "expected"),
    [({}, True, CHEAP), ({"model_name": CHEAP}, True, CHEAP), ({"model": CHEAP}, True, CHEAP), ({}, False, EXPENSIVE), ({"agent_name": "momobot-max"}, True, EXPENSIVE), ({"agent_name": "momobot-max", "model_name": CHEAP}, True, CHEAP)],
)
async def test_staff_default_route_explicit_and_builtin_models_match_worker_and_record(monkeypatch, context, router_enabled, expected):
    h = harness(monkeypatch, role="admin", router_enabled=router_enabled)
    record = await launch(h, context)
    actual = h.worker.await_args.kwargs["config"]
    assert actual["context"]["model_name"] == expected
    assert (await h.store.get(record.run_id))["model_name"] == expected


@pytest.mark.parametrize("bootstrap", [False, True])
@pytest.mark.parametrize(("override", "expected"), [(None, EXPENSIVE), (CHEAP, CHEAP)])
async def test_custom_agent_model_precedes_default_route_but_preserves_staff_override(monkeypatch, override, expected, bootstrap):
    h = harness(monkeypatch, role="admin")
    agent = SimpleNamespace(model=EXPENSIVE, client_id=None, knowledge_scope=None)
    monkeypatch.setattr(services, "_load_scope_agent_config", AsyncMock(return_value=agent))
    record = await launch(h, {"agent_name": "custom-agent", "is_bootstrap": bootstrap, **({"model_name": override} if override else {})})
    assert h.worker.await_args.kwargs["config"]["context"]["model_name"] == expected
    assert (await h.store.get(record.run_id))["model_name"] == expected


async def test_existing_authorized_model_fallback_is_admitted_and_pinned(monkeypatch):
    authorization = {
        "enabled": True,
        "fail_closed": True,
        "default_role": "user",
        "provider": {"use": "deerflow.authz.rbac:RbacAuthorizationProvider", "config": {"roles": {"user": {"models": {"allow": [CHEAP]}}}}},
    }
    h = harness(monkeypatch, role="user", refusal="denied", authorization=authorization)
    # Runtime policy already falls back to this role's permitted model. Meter
    # that permitted model, even when the unused requested model is denylisted.
    record = await launch(h, {"model_name": EXPENSIVE, "user_role": "admin"})
    actual = h.worker.await_args.kwargs["config"]
    assert actual["context"]["user_role"] == "user"
    assert actual["context"]["model_name"] == CHEAP
    assert (await h.store.get(record.run_id))["model_name"] == CHEAP


async def test_a_base_client_is_admitted_and_billed_on_the_base_model(monkeypatch):
    h = harness(monkeypatch, tier="base")
    record = await launch(h, {"agent_name": "finance-bot", "model_name": EXPENSIVE}, config={"configurable": {"model_name": EXPENSIVE}})
    actual = h.worker.await_args.kwargs["config"]
    for section in ("configurable", "context"):
        assert actual[section]["agent_name"] == "momobot-max" and actual[section]["model_name"] == CHEAP
    assert (await h.store.get(record.run_id))["model_name"] == CHEAP


async def test_a_base_client_with_an_unpriced_base_model_is_refused_before_any_run(monkeypatch):
    h = harness(monkeypatch, tier="base", refusal="unpriced-base")
    with pytest.raises(HTTPException) as error:
        await launch(h, {})
    assert error.value.status_code == 402
    h.manager.create_or_reject.assert_not_awaited()
    h.worker.assert_not_awaited()
