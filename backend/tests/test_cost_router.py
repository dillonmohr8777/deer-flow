"""Cost router: routing, cap refusal, missing price, denylist, spend endpoint."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from app.gateway.routers import cost_router as router_module
from deerflow.config.cost_router_config import CostRouterConfig
from deerflow.runtime.cost_router import CostRouterRefusal, admit_run, spend_report
from deerflow.runtime.runs.store.memory import MemoryRunStore

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 10, 15, 12, tzinfo=UTC)
YESTERDAY = datetime(2026, 10, 14, 12, tzinfo=UTC)
LAST_MONTH = datetime(2026, 9, 20, 12, tzinfo=UTC)


def _model(name, provider_id=None):
    return SimpleNamespace(name=name, model=provider_id or name)


def _app_config(**router):
    router.setdefault("enabled", True)
    models = {m.name: m for m in (_model("luna", "openai/gpt-6-luna"), _model("sonnet"), _model("opus"), _model("muse", "meta/muse-spark-1.3-contributor"), _model("mystery"))}
    return SimpleNamespace(
        models=list(models.values()),
        get_model_config=models.get,
        cost_router=CostRouterConfig(**router),
    )


ROUTER = {
    "routes": {
        "bulk": {"model": "luna", "daily_cap_usd": 1.0, "monthly_cap_usd": 10.0},
        "drafting": {"model": "sonnet"},
        "review": {"model": "opus"},
        "oops": {"model": "mystery", "daily_cap_usd": 5},
    },
    "prices": {
        "openai/gpt-6-luna": {"input_per_mtok": 1.0, "output_per_mtok": 2.0},
        "sonnet": {"input_per_mtok": 3.0, "output_per_mtok": 15.0},
        "opus": {"input_per_mtok": 15.0, "output_per_mtok": 75.0},
    },
}


async def _store_with(usage_rows):
    """usage_rows: (created_at, model, input_tokens, output_tokens)."""
    store = MemoryRunStore()
    for i, (created, model, inp, out) in enumerate(usage_rows):
        await store.put(f"r{i}", thread_id="t", model_name=model, created_at=created.isoformat())
        await store.update_run_completion(
            f"r{i}",
            status="success",
            total_input_tokens=inp,
            total_output_tokens=out,
            total_tokens=inp + out,
            token_usage_by_model={model: {"input_tokens": inp, "output_tokens": out, "total_tokens": inp + out}},
        )
    return store


async def test_routes_task_class_to_model():
    cfg = _app_config(**ROUTER)
    store = MemoryRunStore()
    assert await admit_run(cfg, store, None, "bulk", NOW) == "luna"
    assert await admit_run(cfg, store, None, "drafting", NOW) == "sonnet"
    assert await admit_run(cfg, store, None, "review", NOW) == "opus"


async def test_explicit_model_wins_and_unknown_class_refused():
    cfg = _app_config(**ROUTER)
    store = MemoryRunStore()
    assert await admit_run(cfg, store, "sonnet", "bulk", NOW) == "sonnet"
    with pytest.raises(CostRouterRefusal) as exc:
        await admit_run(cfg, store, None, "nope", NOW)
    assert exc.value.status_code == 400


async def test_default_route_used_without_task_class():
    cfg = _app_config(default_route="drafting", **ROUTER)
    assert await admit_run(cfg, MemoryRunStore(), None, None, NOW) == "sonnet"


async def test_daily_cap_refuses_with_clear_message():
    cfg = _app_config(**ROUTER)
    # 1M in + 0.5M out at $1/$2 = $2.00 today, over the $1 daily cap.
    store = await _store_with([(NOW, "openai/gpt-6-luna", 1_000_000, 500_000)])
    with pytest.raises(CostRouterRefusal) as exc:
        await admit_run(cfg, store, None, "bulk", NOW)
    assert exc.value.status_code == 429
    assert "daily cap" in exc.value.message and "$2.00" in exc.value.message and "$1.00" in exc.value.message


async def test_monthly_cap_counts_earlier_days_but_old_months_do_not():
    cfg = _app_config(**ROUTER)
    # $11 yesterday: nothing today, so the daily cap is fine, but the monthly $10 is blown.
    store = await _store_with([(YESTERDAY, "openai/gpt-6-luna", 11_000_000, 0)])
    with pytest.raises(CostRouterRefusal) as exc:
        await admit_run(cfg, store, None, "bulk", NOW)
    assert "monthly cap" in exc.value.message
    old = await _store_with([(LAST_MONTH, "openai/gpt-6-luna", 50_000_000, 0)])
    assert await admit_run(cfg, old, None, "bulk", NOW) == "luna"


async def test_capped_route_without_a_meter_is_refused():
    with pytest.raises(CostRouterRefusal) as exc:
        await admit_run(_app_config(**ROUTER), None, None, "bulk", NOW)
    assert exc.value.status_code == 503


async def test_under_cap_is_admitted():
    cfg = _app_config(**ROUTER)
    store = await _store_with([(NOW, "openai/gpt-6-luna", 100_000, 0)])
    assert await admit_run(cfg, store, None, "bulk", NOW) == "luna"


async def test_model_without_price_is_refused_not_free():
    cfg = _app_config(**ROUTER)
    with pytest.raises(CostRouterRefusal) as exc:
        await admit_run(cfg, MemoryRunStore(), None, "oops", NOW)
    assert exc.value.status_code == 402 and "no price" in exc.value.message


async def test_denylist_blocks_muse_whether_router_is_on_or_off():
    store = MemoryRunStore()
    free_muse = {**ROUTER, "prices": {**ROUTER["prices"], "muse": {"input_per_mtok": 0, "output_per_mtok": 0}}}
    for cfg in (_app_config(enabled=False), _app_config(**ROUTER), _app_config(**free_muse)):
        with pytest.raises(CostRouterRefusal) as exc:
            await admit_run(cfg, store, "muse", None, NOW)  # blocked by provider id meta/muse-*
        assert exc.value.status_code == 403


async def test_disabled_router_passes_other_models_through():
    cfg = _app_config(enabled=False)
    assert await admit_run(cfg, MemoryRunStore(), "mystery", "bulk", NOW) == "mystery"
    assert await admit_run(cfg, MemoryRunStore(), None, "bulk", NOW) is None


async def test_spend_report_per_route_today_and_month():
    cfg = _app_config(**ROUTER)
    store = await _store_with(
        [
            (NOW, "openai/gpt-6-luna", 500_000, 0),
            (YESTERDAY, "openai/gpt-6-luna", 1_000_000, 0),
            (NOW, "sonnet", 0, 1_000_000),
            (NOW, "mystery", 10, 10),
        ]
    )
    report = await spend_report(cfg, store, NOW)
    bulk = report["routes"]["bulk"]
    assert (bulk["today_usd"], bulk["month_usd"]) == (0.5, 1.5)
    assert report["routes"]["drafting"]["month_usd"] == 15.0
    assert report["routes"]["review"]["month_usd"] == 0
    oops = report["routes"]["oops"]
    assert oops["priced"] is False and oops["unpriced_usage"] is True


async def test_endpoint_returns_spend_for_admin(monkeypatch):
    cfg = _app_config(**ROUTER)
    store = await _store_with([(datetime.now(UTC), "sonnet", 0, 1_000_000)])
    app = FastAPI()
    app.state.run_store = store
    app.include_router(router_module.router)

    async def allow(request, *, detail):
        return None

    monkeypatch.setattr(router_module, "get_app_config", lambda: cfg)
    monkeypatch.setattr(router_module, "require_admin_user", allow)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        body = (await c.get("/api/cost-router/spend")).json()
    assert body["routes"]["drafting"]["today_usd"] == 15.0
    assert body["routes"]["bulk"]["daily_cap_usd"] == 1.0


async def test_endpoint_refuses_non_admin(monkeypatch):
    from fastapi import HTTPException

    app = FastAPI()
    app.state.run_store = MemoryRunStore()
    app.include_router(router_module.router)

    async def deny(request, *, detail):
        raise HTTPException(status_code=403, detail=detail)

    monkeypatch.setattr(router_module, "require_admin_user", deny)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.get("/api/cost-router/spend")).status_code == 403


async def test_sql_run_repository_usage_by_model_since(tmp_path):
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
    from deerflow.persistence.run import RunRepository

    await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 't.db'}", sqlite_dir=str(tmp_path))
    try:
        repo = RunRepository(get_session_factory())
        await repo.put("new", thread_id="t", status="running", model_name="sonnet", created_at=NOW.isoformat())
        await repo.update_run_completion("new", status="success", total_input_tokens=7, total_output_tokens=3, total_tokens=10, token_usage_by_model={"sonnet": {"input_tokens": 7, "output_tokens": 3, "total_tokens": 10}})
        await repo.put("legacy", thread_id="t", status="running", model_name="opus", created_at=NOW.isoformat())
        await repo.update_run_completion("legacy", status="success", total_input_tokens=5, total_output_tokens=1, total_tokens=6)
        await repo.put("old", thread_id="t", status="running", model_name="sonnet", created_at=LAST_MONTH.isoformat())
        await repo.update_run_completion("old", status="success", total_input_tokens=999, total_output_tokens=999, total_tokens=1998, token_usage_by_model={"sonnet": {"input_tokens": 999, "output_tokens": 999, "total_tokens": 1998}})
        usage = await repo.usage_by_model_since(datetime(2026, 10, 1, tzinfo=UTC))
    finally:
        await close_engine()
    assert usage == {"sonnet": {"input_tokens": 7, "output_tokens": 3}, "opus": {"input_tokens": 5, "output_tokens": 1}}
