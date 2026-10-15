"""`meta_ads_insights`: read-only Meta Marketing API Insights (GET only)."""

import json
import os
from typing import Any

import httpx
from langchain.tools import tool

from deerflow.community.ads import derive
from deerflow.community.ads.common import AdsToolError, check_dates, error_json, load_credentials, mask, now_iso, require_allowed

API_VERSION = os.getenv("DEERFLOW_META_ADS_API_VERSION", "v21.0")
LEVELS = {"account", "campaign", "adset"}
MAX_ROWS = 1000
FIELDS = "campaign_name,adset_name,spend,impressions,reach,clicks,actions"
# "lead" is Meta's deduplicated total; the others are fallbacks so we never add overlapping counts.
LEAD_TYPES = ("lead", "onsite_conversion.lead_grouped", "offsite_conversion.fb_pixel_lead")


def _leads(actions: Any) -> float | None:
    by_type = {a.get("action_type"): a.get("value") for a in actions or [] if isinstance(a, dict)}
    for t in LEAD_TYPES:
        if t in by_type:
            try:
                return float(by_type[t])
            except (TypeError, ValueError):
                return None
    return None


def _num(v: Any) -> float | None:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def shape_row(raw: dict[str, Any]) -> dict[str, Any]:
    spend, leads = _num(raw.get("spend")), _leads(raw.get("actions"))
    row = {k: raw.get(k) for k in ("campaign_name", "adset_name", "date_start", "date_stop") if raw.get(k)}
    row.update({k: _num(raw.get(k)) for k in ("spend", "impressions", "reach", "clicks")})
    row["leads"] = leads
    row["cpl"] = round(spend / leads, 2) if spend is not None and leads else None
    return row


def run_insights(account_id: str, level: str, start_date: str, end_date: str, monthly: bool, user_id: str | None = None) -> dict[str, Any]:
    creds = load_credentials("meta_ads", user_id)
    account = require_allowed(account_id, creds.get("allowed_account_ids"), "account_id")
    if level not in LEVELS:
        raise AdsToolError(f"level must be one of: {', '.join(sorted(LEVELS))}.")
    check_dates(start_date, end_date)
    token = creds.get("access_token")
    if not token:
        raise AdsToolError("Meta Ads credentials are incomplete (need access_token).")
    params: dict[str, Any] = {"fields": FIELDS, "level": level, "time_range": json.dumps({"since": start_date, "until": end_date}), "limit": 200}
    if monthly:
        params["time_increment"] = "monthly"
    rows: list[dict[str, Any]] = []
    while len(rows) < MAX_ROWS:  # cursor paging; the `next` URL is not followed so the token never leaves headers
        resp = httpx.get(f"https://graph.facebook.com/{API_VERSION}/act_{account}/insights", params=params, headers={"Authorization": f"Bearer {token}"}, timeout=60)
        if resp.status_code != 200:
            msg = (resp.json().get("error", {}).get("message") if resp.headers.get("content-type", "").startswith(("application/json", "text/javascript")) else None) or "request rejected"
            raise AdsToolError(f"Meta API error {resp.status_code}: {msg}")
        data = resp.json()
        rows += [shape_row(r) for r in data.get("data", [])]
        after = data.get("paging", {}).get("cursors", {}).get("after")
        if not (data.get("paging", {}).get("next") and after):
            break
        params["after"] = after
    result: dict[str, Any] = {"source": f"Meta Marketing API, read {now_iso()}, account act_{mask(account)}", "level": level, "row_count": len(rows[:MAX_ROWS]), "rows": rows[:MAX_ROWS]}
    if monthly:
        table = derive.monthly_kpis(rows, "date_start", "spend", "leads", ("impressions", "clicks"))
        result["monthly_kpis"] = table
        result.update(derive.best_month(table))  # shares dicts with `table`, so the rename below covers both
        for m in table:
            m["leads"], m["cpl"] = m.pop("conversions"), m.pop("cost_per_conversion")
    return result


@tool("meta_ads_insights", parse_docstring=True)
def meta_ads_insights_tool(account_id: str, start_date: str, end_date: str, level: str = "campaign", monthly: bool = False) -> str:
    """Read-only Meta Ads Insights (spend, impressions, reach, clicks, leads, CPL) with a source stamp.

    Cite the stamp when using numbers. Only ad accounts linked to the current user can be queried.
    Missing values come back as null, never 0. CPL is null when leads are missing or zero.

    Args:
        account_id: Meta ad account ID (digits; "act_" prefix ok). Must be linked to this user.
        start_date: ISO start date (YYYY-MM-DD).
        end_date: ISO end date (inclusive).
        level: One of account, campaign, adset.
        monthly: If true, break out by month and also return a monthly KPI table and the best month (lowest CPL, needs spend >= 150 and >= 5 leads).
    """
    try:
        return json.dumps(run_insights(account_id, level, start_date, end_date, monthly), ensure_ascii=False)
    except (AdsToolError, httpx.HTTPError, KeyError, ValueError) as exc:
        return error_json(exc)
