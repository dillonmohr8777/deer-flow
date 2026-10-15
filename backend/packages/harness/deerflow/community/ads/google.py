"""`google_ads_report`: read-only GAQL against an allowlist of resources.

Credentials come from the calling user's own file (see common.py); the tool
only queries customer IDs listed there. Only the ``googleAds:search`` endpoint
is ever called, so no write path exists.
"""

import json
import os
import re
from typing import Any

import httpx
from langchain.tools import tool

from deerflow.community.ads import derive
from deerflow.community.ads.common import AdsToolError, check_dates, digits, error_json, load_credentials, mask, now_iso, require_allowed

API_VERSION = os.getenv("DEERFLOW_GOOGLE_ADS_API_VERSION", "v25")
TOKEN_URL = "https://oauth2.googleapis.com/token"
MAX_ROWS = 1000
ALLOWED_RESOURCES = {"campaign", "ad_group", "keyword_view", "search_term_view", "customer"}
_MUTATE_WORDS = re.compile(r"\b(mutate|create|update|remove|delete|set|insert|upsert|alter|drop)\b", re.I)
_STRING_LITERAL = re.compile(r"'[^']*'|\"[^\"]*\"")
_FROM = re.compile(r"\bFROM\s+(\w+(?:\s*,\s*\w+)*)", re.I)
_LIMIT = re.compile(r"\bLIMIT\s+(\d+)\s*$", re.I)


def validate_gaql(query: str) -> str:
    """Return the query to run (LIMIT enforced) or raise AdsToolError."""
    q = (query or "").strip()
    bare = _STRING_LITERAL.sub("''", q)
    if not re.match(r"select\b", bare, re.I):
        raise AdsToolError("Only SELECT queries are allowed.")
    if ";" in bare:
        raise AdsToolError("Multiple statements are not allowed.")
    if _MUTATE_WORDS.search(bare):
        raise AdsToolError("Mutate-like keywords are not allowed; this tool is read-only.")
    sources = _FROM.findall(bare)
    if len(sources) != 1 or sources[0].lower() not in ALLOWED_RESOURCES:
        raise AdsToolError(f"FROM must be exactly one of: {', '.join(sorted(ALLOWED_RESOURCES))}.")
    limit = _LIMIT.search(bare)
    if limit and int(limit.group(1)) > MAX_ROWS:
        raise AdsToolError(f"LIMIT may not exceed {MAX_ROWS}.")
    return q if limit else f"{q} LIMIT {MAX_ROWS}"


def apply_date_range(query: str, start_date: str, end_date: str) -> str:
    check_dates(start_date, end_date)
    clause = f"segments.date BETWEEN '{start_date}' AND '{end_date}'"
    bare = _STRING_LITERAL.sub(lambda m: "x" * len(m.group(0)), query)  # keep offsets
    where = re.search(r"\bWHERE\b", bare, re.I)
    if where:
        return f"{query[: where.end()]} {clause} AND{query[where.end() :]}"
    tail = re.search(r"\b(ORDER\s+BY|LIMIT|PARAMETERS)\b", bare, re.I)
    cut = tail.start() if tail else len(query)
    return f"{query[:cut].rstrip()} WHERE {clause} {query[cut:]}".rstrip()


def _snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def flatten_row(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}

    def walk(node: Any, prefix: str) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{prefix}.{_snake(k)}" if prefix else _snake(k))
        else:
            out[prefix] = node

    walk(row, "")
    micros = out.pop("metrics.cost_micros", None)
    if micros is not None:
        out["metrics.cost"] = round(int(micros) / 1_000_000, 2)
    return out


def _access_token(creds: dict[str, Any]) -> str:
    try:
        resp = httpx.post(
            TOKEN_URL,
            data={
                "client_id": creds["client_id"],
                "client_secret": creds["client_secret"],
                "refresh_token": creds["refresh_token"],
                "grant_type": "refresh_token",
            },
            timeout=20,
        )
    except KeyError:
        raise AdsToolError("Google Ads credentials are incomplete (need client_id, client_secret, refresh_token).") from None
    if resp.status_code != 200:
        raise AdsToolError("Google OAuth token refresh failed; re-run the consent step.")
    return resp.json()["access_token"]


def run_report(customer_id: str, query: str, start_date: str | None, end_date: str | None, monthly_summary: bool, user_id: str | None = None) -> dict[str, Any]:
    creds = load_credentials("google_ads", user_id)
    customer = require_allowed(customer_id, creds.get("allowed_customer_ids"), "customer_id")
    gaql = validate_gaql(query)
    if start_date or end_date:
        gaql = apply_date_range(gaql, start_date or "", end_date or "")
    headers = {"Authorization": f"Bearer {_access_token(creds)}"}
    if login := digits(creds.get("login_customer_id")):
        headers["login-customer-id"] = login
    if dev := creds.get("developer_token"):
        headers["developer-token"] = dev
    rows: list[dict[str, Any]] = []
    page_token = None
    while True:  # googleAds:search pages by token; MAX_ROWS keeps this to a couple of pages
        body: dict[str, Any] = {"query": gaql}
        if page_token:
            body["pageToken"] = page_token
        resp = httpx.post(f"https://googleads.googleapis.com/{API_VERSION}/customers/{customer}/googleAds:search", headers=headers, json=body, timeout=60)
        if resp.status_code != 200:
            msg = (resp.json().get("error", {}).get("message") if resp.headers.get("content-type", "").startswith("application/json") else None) or "request rejected"
            raise AdsToolError(f"Google Ads API error {resp.status_code}: {msg}")
        data = resp.json()
        rows += [flatten_row(r) for r in data.get("results", [])]
        page_token = data.get("nextPageToken")
        if not page_token or len(rows) >= MAX_ROWS:
            break
    result: dict[str, Any] = {"source": f"Google Ads API, read {now_iso()}, customer {mask(customer)}", "query": gaql, "row_count": len(rows), "rows": rows[:MAX_ROWS]}
    if monthly_summary:
        table = derive.monthly_kpis(rows, "segments.month", "metrics.cost", "metrics.conversions", ("metrics.clicks", "metrics.impressions"))
        result["monthly_kpis"] = table
        result.update(derive.best_month(table))
    return result


@tool("google_ads_report", parse_docstring=True)
def google_ads_report_tool(customer_id: str, query: str, start_date: str | None = None, end_date: str | None = None, monthly_summary: bool = False) -> str:
    """Read-only Google Ads report via GAQL, with a source stamp. Cite the stamp when using numbers.

    Allowed FROM resources: campaign, ad_group, keyword_view, search_term_view, customer. SELECT only; max 1000 rows.
    Only customer IDs linked to the current user can be queried. Missing values come back as null, never 0.

    Args:
        customer_id: Google Ads customer ID (digits, dashes ok). Must be linked to this user.
        query: GAQL SELECT, e.g. "SELECT segments.month, metrics.cost_micros, metrics.conversions FROM customer".
        start_date: Optional ISO start date; adds a segments.date filter. Requires end_date.
        end_date: Optional ISO end date (inclusive).
        monthly_summary: If true and the query selects segments.month, also return a monthly KPI table and the best month (lowest cost per conversion, needs spend >= 150 and >= 5 conversions).
    """
    try:
        return json.dumps(run_report(customer_id, query, start_date, end_date, monthly_summary), ensure_ascii=False)
    except (AdsToolError, httpx.HTTPError, KeyError, ValueError) as exc:
        return error_json(exc)
