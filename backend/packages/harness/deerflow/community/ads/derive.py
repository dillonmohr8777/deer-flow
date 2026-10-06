"""Derived helpers: monthly KPI table and best month. Missing is None, never 0."""

from collections import defaultdict
from typing import Any

# Lead-gen rule from the Oct 5 proof: lowest cost per conversion among months with enough volume.
MIN_SPEND = 150.0
MIN_CONVERSIONS = 5.0


def _num(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _sum(values: list[float | None]) -> float | None:
    """None if every value is missing (unavailable), else sum of the known ones."""
    known = [v for v in values if v is not None]
    return sum(known) if known else None


def monthly_kpis(rows: list[dict[str, Any]], month_key: str, spend_key: str, conv_key: str, extra_keys: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    by_month: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        month = row.get(month_key)
        if month:
            by_month[str(month)[:7]].append(row)
    table = []
    for month in sorted(by_month):
        group = by_month[month]
        spend = _sum([_num(r.get(spend_key)) for r in group])
        conv = _sum([_num(r.get(conv_key)) for r in group])
        entry: dict[str, Any] = {"month": month, "spend": spend, "conversions": conv}
        for key in extra_keys:
            entry[key] = _sum([_num(r.get(key)) for r in group])
        entry["cost_per_conversion"] = round(spend / conv, 2) if spend is not None and conv else None
        table.append(entry)
    return table


def best_month(table: list[dict[str, Any]], min_spend: float = MIN_SPEND, min_conversions: float = MIN_CONVERSIONS) -> dict[str, Any]:
    """Lowest cost/conversion among months meeting the minimum-volume rule."""
    rule = f"lowest cost per conversion among months with spend >= {min_spend:g} and conversions >= {min_conversions:g}"
    eligible = [m for m in table if m["cost_per_conversion"] is not None and (m["spend"] or 0) >= min_spend and (m["conversions"] or 0) >= min_conversions]
    if not eligible:
        return {"best_month": None, "rule": rule, "note": "unavailable: no month meets the minimum-volume rule"}
    return {"best_month": min(eligible, key=lambda m: m["cost_per_conversion"]), "rule": rule}
