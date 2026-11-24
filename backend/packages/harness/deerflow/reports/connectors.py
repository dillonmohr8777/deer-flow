"""Plane 0 read-only connector adapter interface for workspace reporting.

Every connector in this module is strictly read-only (no ad mutations, no sends,
no credential persistence in code). Workspace bindings store opaque account and
secret-store references; missing or degraded feeds always report ``pending``,
``stale``, or ``unavailable`` and NEVER fabricate zero lead counts.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from deerflow.reports.schema import (
    VALID_CONNECTOR_KEYS,
    VALID_CONNECTOR_STATUSES,
    ConnectorKey,
    ConnectorStatus,
    validate_lead_category,
)

CONNECTOR_KEYS: tuple[ConnectorKey, ...] = VALID_CONNECTOR_KEYS
DEFAULT_STALE_AFTER_HOURS = 48


@dataclass(frozen=True)
class ConnectorBindingContext:
    """Non-secret workspace binding metadata passed into a read connector."""

    workspace_id: str
    connector_key: ConnectorKey
    status: ConnectorStatus
    external_account_ref: str | None = None
    credential_ref: str | None = None
    last_synced_at: datetime | None = None
    detail: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ConnectorHealthSnapshot:
    """Normalized health state for one Plane 0 connector in one workspace."""

    connector_key: ConnectorKey
    display_name: str
    status: ConnectorStatus
    provides_leads: bool
    capability_summary: str
    external_account_ref: str | None
    last_synced_at: datetime | None
    detail: str
    required_credential_refs: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "connector_key": self.connector_key,
            "display_name": self.display_name,
            "status": self.status,
            "provides_leads": self.provides_leads,
            "capability_summary": self.capability_summary,
            "external_account_ref": self.external_account_ref,
            "last_synced_at": self.last_synced_at.isoformat() if self.last_synced_at else None,
            "detail": self.detail,
            "required_credential_refs": list(self.required_credential_refs),
        }


@dataclass(frozen=True)
class ConnectorReadResult:
    """Result of a Plane 0 read attempt. ``records`` is ``None`` when feed is unavailable/pending."""

    connector_key: ConnectorKey
    status: ConnectorStatus
    records: tuple[dict[str, Any], ...] | None
    detail: str = ""
    synced_at: datetime | None = None


LiveLeadFetcher = Callable[[str, ConnectorBindingContext, datetime, datetime], Awaitable[list[dict[str, Any]]]]


def _utc_aware(ts: datetime | None) -> datetime | None:
    if ts is None:
        return None
    if ts.tzinfo is None:
        return ts.replace(tzinfo=UTC)
    return ts.astimezone(UTC)


class ReportReadConnector(ABC):
    """Abstract Plane 0 read-only reporting connector."""

    key: ConnectorKey
    display_name: str
    provides_leads: bool
    capability_summary: str
    required_credential_refs: tuple[str, ...]

    def __init__(self, *, live_fetcher: LiveLeadFetcher | None = None) -> None:
        self._live_fetcher = live_fetcher

    def _effective_status(
        self,
        binding: ConnectorBindingContext | None,
        *,
        now: datetime | None = None,
    ) -> tuple[ConnectorStatus, str]:
        if binding is None:
            return "pending", "Awaiting workspace account and credential binding."
        if binding.status not in VALID_CONNECTOR_STATUSES:
            return "unavailable", "Connector binding reported an unrecognized status."
        if binding.status == "unavailable":
            return "unavailable", binding.detail or "Connector feed is currently unavailable."
        if binding.status == "pending":
            return "pending", binding.detail or "Connector setup is pending verification."
        if not binding.external_account_ref and not binding.credential_ref:
            return "pending", binding.detail or "Workspace account reference has not been linked."

        anchor = _utc_aware(now) or datetime.now(UTC)
        stale_hours_raw = binding.metadata.get("stale_after_hours", DEFAULT_STALE_AFTER_HOURS)
        try:
            stale_hours = max(1, int(stale_hours_raw))
        except (TypeError, ValueError):
            stale_hours = DEFAULT_STALE_AFTER_HOURS

        synced = _utc_aware(binding.last_synced_at)
        if binding.status == "stale":
            return "stale", binding.detail or f"Last sync is older than {stale_hours} hours."
        if synced is not None and anchor - synced > timedelta(hours=stale_hours):
            return "stale", binding.detail or f"Last sync is older than {stale_hours} hours."
        return "connected", binding.detail or "Read-only feed connected."

    async def check_health(
        self,
        workspace_id: str,
        binding: ConnectorBindingContext | None,
        *,
        now: datetime | None = None,
    ) -> ConnectorHealthSnapshot:
        """Evaluate fail-closed health state for *workspace_id* without exposing secrets."""
        if binding is not None and binding.workspace_id != workspace_id:
            raise ValueError("Connector binding workspace mismatch")
        status, detail = self._effective_status(binding, now=now)
        return ConnectorHealthSnapshot(
            connector_key=self.key,
            display_name=self.display_name,
            status=status,
            provides_leads=self.provides_leads,
            capability_summary=self.capability_summary,
            external_account_ref=binding.external_account_ref if binding else None,
            last_synced_at=_utc_aware(binding.last_synced_at) if binding else None,
            detail=detail,
            required_credential_refs=self.required_credential_refs,
        )

    @abstractmethod
    async def fetch_leads(
        self,
        workspace_id: str,
        binding: ConnectorBindingContext | None,
        start_at: datetime,
        end_at: datetime,
        *,
        now: datetime | None = None,
    ) -> ConnectorReadResult:
        """Read verified lead records for a period, or return ``records=None`` when unavailable."""

    async def _run_bound_fetch(
        self,
        workspace_id: str,
        binding: ConnectorBindingContext | None,
        start_at: datetime,
        end_at: datetime,
        *,
        now: datetime | None = None,
    ) -> ConnectorReadResult:
        health = await self.check_health(workspace_id, binding, now=now)
        if not self.provides_leads:
            return ConnectorReadResult(
                connector_key=self.key,
                status=health.status,
                records=None,
                detail="Visibility connector does not emit lead records.",
                synced_at=health.last_synced_at,
            )
        if binding is None or health.status in ("pending", "unavailable"):
            return ConnectorReadResult(
                connector_key=self.key,
                status=health.status,
                records=None,
                detail=health.detail,
                synced_at=health.last_synced_at,
            )
        if self._live_fetcher is None:
            return ConnectorReadResult(
                connector_key=self.key,
                status=health.status,
                records=None,
                detail="Using persisted synced records; no live Plane 0 fetcher bound in this process.",
                synced_at=health.last_synced_at,
            )
        raw_records = await self._live_fetcher(workspace_id, binding, start_at, end_at)
        validated: list[dict[str, Any]] = []
        for item in raw_records:
            category = validate_lead_category(item.get("lead_type"))
            validated.append({**item, "lead_type": category, "source_connector": self.key})
        return ConnectorReadResult(
            connector_key=self.key,
            status=health.status,
            records=tuple(validated),
            detail=health.detail,
            synced_at=_utc_aware(now) or datetime.now(UTC),
        )


class GoogleAdsReadConnector(ReportReadConnector):
    key: ConnectorKey = "google_ads"
    display_name = "Google Ads"
    provides_leads = True
    capability_summary = "Verified form, call, and booking conversion actions (clicks excluded)"
    required_credential_refs = ("GOOGLE_ADS_DEVELOPER_TOKEN", "GOOGLE_ADS_OAUTH_REF")

    async def fetch_leads(
        self,
        workspace_id: str,
        binding: ConnectorBindingContext | None,
        start_at: datetime,
        end_at: datetime,
        *,
        now: datetime | None = None,
    ) -> ConnectorReadResult:
        return await self._run_bound_fetch(workspace_id, binding, start_at, end_at, now=now)


class Ga4ReadConnector(ReportReadConnector):
    key: ConnectorKey = "ga4"
    display_name = "Google Analytics 4"
    provides_leads = True
    capability_summary = "Key conversion events mapped to verified lead categories"
    required_credential_refs = ("GA4_PROPERTY_CREDENTIALS_REF",)

    async def fetch_leads(
        self,
        workspace_id: str,
        binding: ConnectorBindingContext | None,
        start_at: datetime,
        end_at: datetime,
        *,
        now: datetime | None = None,
    ) -> ConnectorReadResult:
        return await self._run_bound_fetch(workspace_id, binding, start_at, end_at, now=now)


class GscBigQueryReadConnector(ReportReadConnector):
    key: ConnectorKey = "gsc_bigquery"
    display_name = "GSC BigQuery"
    provides_leads = False
    capability_summary = "Organic search query visibility and landing-page attribution (never counted as leads)"
    required_credential_refs = ("GCP_BIGQUERY_PROJECT_REF", "GSC_BIGQUERY_DATASET")

    async def fetch_leads(
        self,
        workspace_id: str,
        binding: ConnectorBindingContext | None,
        start_at: datetime,
        end_at: datetime,
        *,
        now: datetime | None = None,
    ) -> ConnectorReadResult:
        return await self._run_bound_fetch(workspace_id, binding, start_at, end_at, now=now)


class MetaAdsReadConnector(ReportReadConnector):
    key: ConnectorKey = "meta_ads"
    display_name = "Meta Ads"
    provides_leads = True
    capability_summary = "Lead form submissions and booked appointments (link clicks excluded)"
    required_credential_refs = ("META_ADS_TOKEN_REF",)

    async def fetch_leads(
        self,
        workspace_id: str,
        binding: ConnectorBindingContext | None,
        start_at: datetime,
        end_at: datetime,
        *,
        now: datetime | None = None,
    ) -> ConnectorReadResult:
        return await self._run_bound_fetch(workspace_id, binding, start_at, end_at, now=now)


class WhatConvertsReadConnector(ReportReadConnector):
    key: ConnectorKey = "whatconverts"
    display_name = "WhatConverts"
    provides_leads = True
    capability_summary = "Named-lead match-back across tracked calls, web forms, and bookings"
    required_credential_refs = ("WHATCONVERTS_API_TOKEN_REF",)

    async def fetch_leads(
        self,
        workspace_id: str,
        binding: ConnectorBindingContext | None,
        start_at: datetime,
        end_at: datetime,
        *,
        now: datetime | None = None,
    ) -> ConnectorReadResult:
        return await self._run_bound_fetch(workspace_id, binding, start_at, end_at, now=now)


class GoogleSheetsReadConnector(ReportReadConnector):
    key: ConnectorKey = "google_sheets"
    display_name = "Google Sheets"
    provides_leads = True
    capability_summary = "Verified lead log and appointment match-back spreadsheets"
    required_credential_refs = ("GOOGLE_SHEETS_CREDENTIALS_REF",)

    async def fetch_leads(
        self,
        workspace_id: str,
        binding: ConnectorBindingContext | None,
        start_at: datetime,
        end_at: datetime,
        *,
        now: datetime | None = None,
    ) -> ConnectorReadResult:
        return await self._run_bound_fetch(workspace_id, binding, start_at, end_at, now=now)


class ConnectorRegistry:
    """Ordered registry of Plane 0 read connectors."""

    def __init__(self, adapters: tuple[ReportReadConnector, ...] | None = None) -> None:
        items = adapters or (
            GoogleAdsReadConnector(),
            Ga4ReadConnector(),
            GscBigQueryReadConnector(),
            MetaAdsReadConnector(),
            WhatConvertsReadConnector(),
            GoogleSheetsReadConnector(),
        )
        self._adapters: dict[ConnectorKey, ReportReadConnector] = {adapter.key: adapter for adapter in items}

    def all(self) -> tuple[ReportReadConnector, ...]:
        return tuple(self._adapters[key] for key in CONNECTOR_KEYS if key in self._adapters)

    def get(self, key: ConnectorKey) -> ReportReadConnector:
        if key not in self._adapters:
            raise KeyError(f"Unknown report connector: {key}")
        return self._adapters[key]

    def register(self, adapter: ReportReadConnector) -> None:
        self._adapters[adapter.key] = adapter


DEFAULT_CONNECTOR_REGISTRY = ConnectorRegistry()
