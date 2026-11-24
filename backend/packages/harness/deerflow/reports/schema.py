"""Strict reporting schema invariants for workspace Reports & Leads.

Enforces three core guarantees:
1. Verified lead totals are strict non-negative integers and NEVER include
   non-lead engagement signals such as clicks, impressions, sessions, or pageviews.
2. Missing, pending, or unavailable data connectors yield ``None`` metric values
   with an explicit ``pending`` or ``unavailable`` data state -- never silent zeros.
3. Attached review document URLs are restricted to HTTPS Google Docs / Drive links.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from urllib.parse import urlparse

ReportingPeriod = Literal["last_7d", "last_30d", "this_month", "last_month"]
ConnectorKey = Literal["google_ads", "ga4", "gsc_bigquery", "meta_ads", "whatconverts", "google_sheets"]
ConnectorStatus = Literal["connected", "stale", "pending", "unavailable"]
LeadCategory = Literal["form", "call", "appointment"]
MatchStatus = Literal["matched", "unmatched", "pending_verification"]
MatchConfidence = Literal["high", "medium", "low", "unverified"]
ReviewDocStatus = Literal["pending_review", "approved", "needs_edits"]
DataState = Literal["verified", "partial", "pending", "unavailable"]

DEFAULT_APPOINTMENT_LABEL = "Booked appointments"

VALID_PERIODS: tuple[ReportingPeriod, ...] = ("last_7d", "last_30d", "this_month", "last_month")
VALID_CONNECTOR_KEYS: tuple[ConnectorKey, ...] = (
    "google_ads",
    "ga4",
    "gsc_bigquery",
    "meta_ads",
    "whatconverts",
    "google_sheets",
)
VALID_CONNECTOR_STATUSES: tuple[ConnectorStatus, ...] = ("connected", "stale", "pending", "unavailable")
VALID_LEAD_CATEGORIES: tuple[LeadCategory, ...] = ("form", "call", "appointment")
VALID_MATCH_STATUSES: tuple[MatchStatus, ...] = ("matched", "unmatched", "pending_verification")
VALID_MATCH_CONFIDENCES: tuple[MatchConfidence, ...] = ("high", "medium", "low", "unverified")
VALID_REVIEW_DOC_STATUSES: tuple[ReviewDocStatus, ...] = ("pending_review", "approved", "needs_edits")

EXCLUDED_NON_LEAD_SIGNALS: tuple[str, ...] = ("clicks", "impressions", "sessions", "pageviews")
NON_LEAD_METRIC_TYPES: frozenset[str] = frozenset(
    {
        "click",
        "clicks",
        "ad_click",
        "link_click",
        "outbound_click",
        "impression",
        "impressions",
        "pageview",
        "pageviews",
        "page_view",
        "session",
        "sessions",
        "visit",
        "visits",
        "ctr",
        "reach",
    }
)

_ALLOWED_DOC_HOSTS: frozenset[str] = frozenset({"docs.google.com", "drive.google.com"})
_MAX_DOC_URL_LENGTH = 1024


def require_strict_int(value: Any, field_name: str) -> int:
    """Validate that *value* is a non-negative integer (rejecting booleans and floats)."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer, got {type(value).__name__}")
    if value < 0:
        raise ValueError(f"{field_name} must be non-negative, got {value}")
    return value


def validate_lead_category(value: Any) -> LeadCategory:
    """Ensure a lead record belongs to an explicit verified lead category, never clicks."""
    if not isinstance(value, str):
        raise ValueError("lead_type must be one of: form, call, appointment")
    normalized = value.strip().lower()
    if normalized in NON_LEAD_METRIC_TYPES:
        raise ValueError(f"Non-lead engagement signal '{normalized}' cannot be counted as a lead")
    if normalized not in VALID_LEAD_CATEGORIES:
        raise ValueError(f"Unsupported lead_type '{normalized}'; expected one of {', '.join(VALID_LEAD_CATEGORIES)}")
    return normalized  # type: ignore[return-value]


def validate_google_doc_url(raw_url: str) -> str:
    """Validate that a review document URL is an HTTPS Google Docs or Drive link."""
    if not isinstance(raw_url, str):
        raise ValueError("Google Doc URL must be a string")
    url = raw_url.strip()
    if not url:
        raise ValueError("Google Doc URL is required")
    if len(url) > _MAX_DOC_URL_LENGTH:
        raise ValueError(f"Google Doc URL must be at most {_MAX_DOC_URL_LENGTH} characters")
    if any(ord(ch) < 32 or ch.isspace() for ch in url):
        raise ValueError("Google Doc URL must not contain whitespace or control characters")
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError("Google Doc URL must use https://")
    if parsed.username or parsed.password:
        raise ValueError("Google Doc URL must not embed credentials")
    host = (parsed.hostname or "").lower()
    if host not in _ALLOWED_DOC_HOSTS:
        raise ValueError("Review document URL must point to docs.google.com or drive.google.com")
    if not parsed.path or parsed.path == "/":
        raise ValueError("Google Doc URL must include a document path")
    return url


def resolve_period_window(period: ReportingPeriod, now: datetime | None = None) -> tuple[datetime, datetime]:
    """Return an inclusive-start, inclusive-end UTC reporting window for *period*."""
    anchor = (now or datetime.now(UTC)).astimezone(UTC)
    if period == "last_7d":
        return anchor - timedelta(days=7), anchor
    if period == "last_30d":
        return anchor - timedelta(days=30), anchor
    if period == "this_month":
        month_start = anchor.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return month_start, anchor
    if period == "last_month":
        this_month_start = anchor.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        prev_month_end = this_month_start - timedelta(microseconds=1)
        prev_month_start = prev_month_end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return prev_month_start, prev_month_end
    raise ValueError(f"Unsupported reporting period: {period}")


@dataclass(frozen=True)
class LeadKpiSummary:
    """Strict integer KPI rollup. Never substitutes 0 for unconfigured/missing feeds."""

    total_leads: int | None
    forms: int | None
    calls: int | None
    appointments: int | None
    appointment_label: str
    data_state: DataState
    connected_lead_sources: tuple[str, ...]
    pending_lead_sources: tuple[str, ...]
    unavailable_lead_sources: tuple[str, ...]
    excluded_non_lead_signals: tuple[str, ...] = EXCLUDED_NON_LEAD_SIGNALS

    def __post_init__(self) -> None:
        values = (self.total_leads, self.forms, self.calls, self.appointments)
        if all(v is None for v in values):
            if self.data_state not in ("pending", "unavailable"):
                raise ValueError("Null KPI totals require a pending or unavailable data_state")
            return
        if any(v is None for v in values):
            raise ValueError("KPI counts must either all be integers or all be None when feeds are unavailable")
        total = require_strict_int(self.total_leads, "total_leads")
        forms = require_strict_int(self.forms, "forms")
        calls = require_strict_int(self.calls, "calls")
        appointments = require_strict_int(self.appointments, "appointments")
        if total != forms + calls + appointments:
            raise ValueError(f"total_leads ({total}) must equal forms + calls + appointments ({forms + calls + appointments})")


def aggregate_lead_kpis(
    leads: Iterable[Mapping[str, Any]],
    connector_snapshots: Iterable[Mapping[str, Any]],
    *,
    appointment_label: str = DEFAULT_APPOINTMENT_LABEL,
) -> LeadKpiSummary:
    """Compute strict integer lead KPIs while refusing to treat missing feeds as 0."""
    label = appointment_label.strip() or DEFAULT_APPOINTMENT_LABEL
    lead_sources = [snap for snap in connector_snapshots if snap.get("provides_leads", False)]
    connected = tuple(str(snap["connector_key"]) for snap in lead_sources if snap.get("status") in ("connected", "stale"))
    pending = tuple(str(snap["connector_key"]) for snap in lead_sources if snap.get("status") == "pending")
    unavailable = tuple(str(snap["connector_key"]) for snap in lead_sources if snap.get("status") == "unavailable")
    stale_only = any(snap.get("status") == "stale" for snap in lead_sources)

    lead_list = list(leads)
    # Fail closed: if no lead-bearing connector is connected/stale and no verified
    # lead rows have ever been ingested for this workspace, emit None instead of 0.
    if not connected and not lead_list:
        data_state: DataState = "unavailable" if (unavailable and not pending) else "pending"
        return LeadKpiSummary(
            total_leads=None,
            forms=None,
            calls=None,
            appointments=None,
            appointment_label=label,
            data_state=data_state,
            connected_lead_sources=connected,
            pending_lead_sources=pending,
            unavailable_lead_sources=unavailable,
        )

    forms = 0
    calls = 0
    appointments = 0
    for record in lead_list:
        category = validate_lead_category(record.get("lead_type"))
        if category == "form":
            forms += 1
        elif category == "call":
            calls += 1
        elif category == "appointment":
            appointments += 1

    total = forms + calls + appointments
    if pending or unavailable or stale_only or not connected:
        state: DataState = "partial"
    else:
        state = "verified"

    return LeadKpiSummary(
        total_leads=total,
        forms=forms,
        calls=calls,
        appointments=appointments,
        appointment_label=label,
        data_state=state,
        connected_lead_sources=connected,
        pending_lead_sources=pending,
        unavailable_lead_sources=unavailable,
    )
