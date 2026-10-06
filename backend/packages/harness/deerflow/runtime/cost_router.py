"""Cost router: pick the model for a task class and refuse runs that bust a USD cap.

Spend = recorded token usage (runs table) x the price table in config. A model
with no price is never free: admission refuses it and the report flags it.
Periods are UTC calendar day and month.
"""

from __future__ import annotations

from datetime import UTC, datetime


class CostRouterRefusal(Exception):
    """User-facing refusal. ``status_code`` is the HTTP code the gateway returns."""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _names(app_config, model: str) -> set[str]:
    """A model's config name plus its provider model id: usage rows use either."""
    mc = app_config.get_model_config(model)
    return {model} | ({mc.model} if mc is not None and getattr(mc, "model", None) else set())


def _price(cfg, names):
    return next((cfg.prices[n] for n in names if n in cfg.prices), None)


def _cost(price, usage) -> float:
    return (usage["input_tokens"] * price.input_per_mtok + usage["output_tokens"] * price.output_per_mtok) / 1_000_000


def _route_spend(app_config, route, usage: dict) -> tuple[float, bool]:
    """USD spent on the route's model, and whether usage exists with no price."""
    names = _names(app_config, route.model)
    price = _price(app_config.cost_router, names)
    used = [u for k, u in usage.items() if k in names and u["input_tokens"] + u["output_tokens"] > 0]
    if price is None:
        return 0.0, bool(used)
    return sum(_cost(price, u) for u in used), False


def period_starts(now: datetime) -> tuple[datetime, datetime]:
    now = now.astimezone(UTC)
    return now.replace(hour=0, minute=0, second=0, microsecond=0), now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def spend_report(app_config, run_store, now: datetime | None = None) -> dict:
    """Spend per route for today and this month, in USD."""
    cfg = app_config.cost_router
    day, month = period_starts(now or datetime.now(UTC))
    day_usage = await run_store.usage_by_model_since(day)
    month_usage = await run_store.usage_by_model_since(month)
    routes = {}
    for name, route in cfg.routes.items():
        d, d_unpriced = _route_spend(app_config, route, day_usage)
        m, m_unpriced = _route_spend(app_config, route, month_usage)
        routes[name] = {
            "model": route.model,
            "today_usd": round(d, 6),
            "month_usd": round(m, 6),
            "daily_cap_usd": route.daily_cap_usd,
            "monthly_cap_usd": route.monthly_cap_usd,
            "priced": _price(cfg, _names(app_config, route.model)) is not None,
            "unpriced_usage": d_unpriced or m_unpriced,
        }
    return {"enabled": cfg.enabled, "routes": routes}


async def admit_run(app_config, run_store, model_name: str | None, task_class: str | None, now: datetime | None = None) -> str | None:
    """Return the model to run on, or raise CostRouterRefusal.

    An explicit ``model_name`` wins over routing but is still checked against
    the denylist and, if it is a route's model, that route's caps.
    """
    cfg = app_config.cost_router
    if model_name is None and cfg.enabled:
        key = task_class or cfg.default_route
        if key is not None:
            route = cfg.routes.get(key)
            if route is None:
                raise CostRouterRefusal(400, f"Unknown task class {key!r}. Configured: {sorted(cfg.routes)}.")
            model_name = route.model

    effective = model_name or (app_config.models[0].name if app_config.models else None)
    if effective is None:
        return model_name
    names = _names(app_config, effective)
    if cfg.is_denied(*names):
        raise CostRouterRefusal(403, f"Model {effective!r} is blocked by the cost router denylist.")
    if not cfg.enabled:
        return model_name

    if _price(cfg, names) is None:
        raise CostRouterRefusal(402, f"Model {effective!r} has no price in cost_router.prices, so its spend cannot be metered. Add a price or pick another model.")

    owned = [(n, r) for n, r in cfg.routes.items() if r.model == effective and (r.daily_cap_usd or r.monthly_cap_usd)]
    if owned and run_store is None:
        raise CostRouterRefusal(503, "Spend meter unavailable, so the cap on this route cannot be checked.")
    day, month = period_starts(now or datetime.now(UTC))
    for name, route in owned:
        for label, since, cap in (("daily", day, route.daily_cap_usd), ("monthly", month, route.monthly_cap_usd)):
            if cap is None:
                continue
            spent, _ = _route_spend(app_config, route, await run_store.usage_by_model_since(since))
            if spent >= cap:
                raise CostRouterRefusal(429, f"Route {name!r} hit its {label} cap: ${spent:.2f} spent of ${cap:.2f}. Try again after the {label} reset (UTC) or raise the cap.")
    return model_name
