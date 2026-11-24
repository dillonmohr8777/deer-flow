"""Workspace-scoped Reports & Leads tests: schema invariants, Plane 0 adapters, API isolation, and migration."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import pytest_asyncio
from alembic import command
from fastapi import FastAPI
from org_isolation_fixtures import ORG_A, ORG_B, ORG_S, USER_A, USER_B, USER_C, auth_headers, org_world  # noqa: F401
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import create_async_engine

from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.client_boundary import is_client_allowed_route
from app.gateway.routers import reports
from deerflow.persistence.audit_events import AuditEventRepository
from deerflow.persistence.bootstrap import _get_alembic_config
from deerflow.persistence.reports import ReportsRepository
from deerflow.persistence.user.model import UserRow
from deerflow.reports.connectors import (
    DEFAULT_CONNECTOR_REGISTRY,
    ConnectorBindingContext,
    GoogleAdsReadConnector,
    GscBigQueryReadConnector,
)
from deerflow.reports.schema import (
    DEFAULT_APPOINTMENT_LABEL,
    LeadKpiSummary,
    aggregate_lead_kpis,
    require_strict_int,
    resolve_period_window,
    validate_google_doc_url,
    validate_lead_category,
)


def test_zero_clicks_in_leads_invariant():
    assert validate_lead_category("form") == "form"
    assert validate_lead_category("CALL") == "call"
    assert validate_lead_category("appointment") == "appointment"

    for bad_signal in ("click", "clicks", "ad_click", "link_click", "impression", "impressions", "pageview", "session", "ctr"):
        with pytest.raises(ValueError, match="Non-lead engagement signal"):
            validate_lead_category(bad_signal)

    with pytest.raises(ValueError, match="Unsupported lead_type"):
        validate_lead_category("unknown_event")


def test_strict_integer_kpi_invariants_and_missing_feeds_never_zero():
    with pytest.raises(ValueError, match="integer"):
        require_strict_int(12.5, "total_leads")
    with pytest.raises(ValueError, match="integer"):
        require_strict_int(True, "total_leads")
    with pytest.raises(ValueError, match="non-negative"):
        require_strict_int(-1, "total_leads")

    # Mismatched component sum is rejected.
    with pytest.raises(ValueError, match="must equal"):
        LeadKpiSummary(
            total_leads=5,
            forms=1,
            calls=1,
            appointments=1,
            appointment_label=DEFAULT_APPOINTMENT_LABEL,
            data_state="verified",
            connected_lead_sources=("google_ads",),
            pending_lead_sources=(),
            unavailable_lead_sources=(),
        )

    # All connectors pending -> None totals, NEVER 0.
    pending_connectors = [
        {"connector_key": "google_ads", "status": "pending", "provides_leads": True},
        {"connector_key": "whatconverts", "status": "pending", "provides_leads": True},
        {"connector_key": "gsc_bigquery", "status": "connected", "provides_leads": False},
    ]
    pending_summary = aggregate_lead_kpis([], pending_connectors)
    assert pending_summary.data_state == "pending"
    assert pending_summary.total_leads is None
    assert pending_summary.forms is None
    assert pending_summary.calls is None
    assert pending_summary.appointments is None

    # All lead connectors unavailable -> unavailable state and None totals, NEVER 0.
    unavailable_connectors = [
        {"connector_key": "google_ads", "status": "unavailable", "provides_leads": True},
        {"connector_key": "whatconverts", "status": "unavailable", "provides_leads": True},
    ]
    unavailable_summary = aggregate_lead_kpis([], unavailable_connectors)
    assert unavailable_summary.data_state == "unavailable"
    assert unavailable_summary.total_leads is None

    # Explicitly connected lead connector with zero leads -> verified integer 0.
    connected_connectors = [
        {"connector_key": "google_ads", "status": "connected", "provides_leads": True},
    ]
    zero_verified = aggregate_lead_kpis([], connected_connectors)
    assert zero_verified.data_state == "verified"
    assert zero_verified.total_leads == 0
    assert zero_verified.forms == 0
    assert zero_verified.calls == 0
    assert zero_verified.appointments == 0


def test_google_doc_url_validation_and_period_windows():
    ok = validate_google_doc_url("  https://docs.google.com/document/d/synthetic-id-123/edit  ")
    assert ok == "https://docs.google.com/document/d/synthetic-id-123/edit"
    assert validate_google_doc_url("https://drive.google.com/file/d/synthetic-file-1/view").startswith("https://drive.google.com/")

    for bad_url in (
        "",
        "http://docs.google.com/document/d/insecure",
        "javascript:alert(1)",
        "https://example.invalid/document/d/123",
        "https://user:pass" + "@docs.google.com/document/d/123",
        "https://docs.google.com/",
        "https://docs.google.com/document/d/has space",
    ):
        with pytest.raises(ValueError):
            validate_google_doc_url(bad_url)

    anchor = datetime(2026, 11, 24, 15, 0, tzinfo=UTC)
    s7, e7 = resolve_period_window("last_7d", now=anchor)
    assert e7 - s7 == timedelta(days=7)
    sm, em = resolve_period_window("this_month", now=anchor)
    assert sm == datetime(2026, 11, 1, 0, 0, tzinfo=UTC) and em == anchor
    slm, elm = resolve_period_window("last_month", now=anchor)
    assert slm == datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
    assert elm.year == 2026 and elm.month == 10 and elm.day == 31


@pytest.mark.asyncio
async def test_plane0_connector_adapters_fail_closed_and_detect_staleness():
    now = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)
    adapters = DEFAULT_CONNECTOR_REGISTRY.all()
    assert [a.key for a in adapters] == ["google_ads", "ga4", "gsc_bigquery", "meta_ads", "whatconverts", "google_sheets"]

    gads = GoogleAdsReadConnector()
    unbound_health = await gads.check_health("ws-1", None, now=now)
    assert unbound_health.status == "pending"
    unbound_read = await gads.fetch_leads("ws-1", None, now - timedelta(days=7), now, now=now)
    assert unbound_read.status == "pending"
    assert unbound_read.records is None

    stale_binding = ConnectorBindingContext(
        workspace_id="ws-1",
        connector_key="google_ads",
        status="connected",
        external_account_ref="acct-001",
        credential_ref="GOOGLE_ADS_OAUTH_REF",
        last_synced_at=now - timedelta(hours=72),
    )
    stale_health = await gads.check_health("ws-1", stale_binding, now=now)
    assert stale_health.status == "stale"

    with pytest.raises(ValueError, match="workspace mismatch"):
        await gads.check_health("ws-other", stale_binding, now=now)

    # Visibility-only connector never produces lead records.
    gsc = GscBigQueryReadConnector()
    gsc_binding = ConnectorBindingContext(
        workspace_id="ws-1",
        connector_key="gsc_bigquery",
        status="connected",
        external_account_ref="dataset-001",
        credential_ref="GCP_BIGQUERY_PROJECT_REF",
        last_synced_at=now - timedelta(hours=1),
    )
    gsc_read = await gsc.fetch_leads("ws-1", gsc_binding, now - timedelta(days=7), now, now=now)
    assert gsc_read.status == "connected"
    assert gsc_read.records is None

    # Live fetcher that attempts to sneak clicks into leads is rejected.
    async def bad_fetcher(_ws, _binding, _start, _end):
        return [{"lead_name": "Synthetic Click", "lead_type": "click"}]

    guarded_adapter = GoogleAdsReadConnector(live_fetcher=bad_fetcher)
    fresh_binding = ConnectorBindingContext(
        workspace_id="ws-1",
        connector_key="google_ads",
        status="connected",
        external_account_ref="acct-001",
        credential_ref="GOOGLE_ADS_OAUTH_REF",
        last_synced_at=now - timedelta(hours=1),
    )
    with pytest.raises(ValueError, match="Non-lead engagement signal"):
        await guarded_adapter.fetch_leads("ws-1", fresh_binding, now - timedelta(days=7), now, now=now)


@pytest_asyncio.fixture
async def reports_app(org_world, monkeypatch):  # noqa: F811
    from types import SimpleNamespace

    async def _db_user_from_cookie(request):
        uid = request.cookies["access_token"]
        async with org_world() as session:
            row = await session.get(UserRow, uid)
        role = row.system_role if row is not None else "user"
        email = row.email if row is not None else f"{uid}@example.com"
        return SimpleNamespace(id=uid, system_role=role, email=email)

    monkeypatch.setattr("app.gateway.deps.get_current_user_from_request", _db_user_from_cookie)
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.state.reports_repo = ReportsRepository(org_world)
    app.state.audit_repo = AuditEventRepository(org_world)
    app.include_router(reports.router)
    return app, org_world


def _http(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_reports_api_missing_feeds_pending_never_zero_and_workspace_isolation(reports_app):
    app, sf = reports_app
    repo: ReportsRepository = app.state.reports_repo
    now = datetime.now(UTC)

    # Seed ORG_A with connected lead sources + custom appointment label + 4 verified leads (1 outside 7d).
    await repo.set_appointment_label(ORG_A, "Booked consultations", updated_by=USER_A)
    await repo.upsert_connector_binding(
        ORG_A,
        connector_key="google_ads",
        status="connected",
        external_account_ref="ads-acct-synthetic-a",
        credential_ref="GOOGLE_ADS_OAUTH_REF",
        last_synced_at=now - timedelta(hours=2),
    )
    await repo.upsert_connector_binding(
        ORG_A,
        connector_key="whatconverts",
        status="connected",
        external_account_ref="wc-profile-synthetic-a",
        credential_ref="WHATCONVERTS_API_TOKEN_REF",
        last_synced_at=now - timedelta(hours=1),
    )
    await repo.record_lead(
        ORG_A,
        lead_name="Synthetic Contact Alpha",
        lead_type="form",
        channel="google_ads",
        source_connector="google_ads",
        campaign_name="Search Core",
        match_status="matched",
        match_confidence="high",
        occurred_at=now - timedelta(days=2),
    )
    await repo.record_lead(
        ORG_A,
        lead_name="Synthetic Contact Beta",
        lead_type="call",
        channel="google_ads",
        source_connector="whatconverts",
        campaign_name="Search Core",
        match_status="matched",
        match_confidence="high",
        occurred_at=now - timedelta(days=3),
    )
    await repo.record_lead(
        ORG_A,
        lead_name="Synthetic Contact Gamma",
        lead_type="appointment",
        channel="meta_ads",
        source_connector="whatconverts",
        campaign_name="Retargeting",
        match_status="pending_verification",
        match_confidence="medium",
        occurred_at=now - timedelta(days=15),
    )

    async with _http(app) as client:
        # Unauthenticated request fails closed (401).
        assert (await client.get("/api/reports/summary")).status_code == 401

        # ORG_B has zero bound connectors -> pending state with None counts (NEVER 0) and zero visibility into ORG_A.
        res_b = await client.get("/api/reports/summary?period=last_30d", headers=auth_headers(USER_B, ORG_B))
        assert res_b.status_code == 200, res_b.text
        body_b = res_b.json()
        assert body_b["workspace_id"] == ORG_B
        assert body_b["kpis"]["data_state"] == "pending"
        assert body_b["kpis"]["total_leads"] is None
        assert body_b["kpis"]["forms"] is None
        assert body_b["kpis"]["calls"] is None
        assert body_b["kpis"]["appointments"] is None
        assert body_b["kpis"]["appointment_label"] == DEFAULT_APPOINTMENT_LABEL
        assert body_b["connectors_summary"] == {"connected": 0, "stale": 0, "pending": 6, "unavailable": 0}

        leads_b = await client.get("/api/reports/leads?period=last_30d", headers=auth_headers(USER_B, ORG_B))
        assert leads_b.status_code == 200
        assert leads_b.json()["leads"] == []
        assert leads_b.json()["data_state"] == "pending"

        # ORG_A gets exact integer verified counts across periods and custom appointment_label.
        res_a_30 = await client.get("/api/reports/summary?period=last_30d", headers=auth_headers(USER_A, ORG_A))
        assert res_a_30.status_code == 200, res_a_30.text
        kpis_30 = res_a_30.json()["kpis"]
        assert kpis_30["total_leads"] == 3
        assert kpis_30["forms"] == 1
        assert kpis_30["calls"] == 1
        assert kpis_30["appointments"] == 1
        assert kpis_30["matched_leads"] == 2
        assert kpis_30["appointment_label"] == "Booked consultations"
        assert kpis_30["data_state"] == "partial"

        res_a_7 = await client.get("/api/reports/summary?period=last_7d", headers=auth_headers(USER_A, ORG_A))
        assert res_a_7.status_code == 200
        assert res_a_7.json()["kpis"]["total_leads"] == 2
        assert res_a_7.json()["kpis"]["appointments"] == 0

        # Leads endpoint filters cleanly and rejects non-lead click filter (422).
        calls_only = await client.get("/api/reports/leads?period=last_30d&lead_type=call", headers=auth_headers(USER_A, ORG_A))
        assert calls_only.status_code == 200
        assert [row["lead_name"] for row in calls_only.json()["leads"]] == ["Synthetic Contact Beta"]

        click_filter = await client.get("/api/reports/leads?period=last_30d&lead_type=click", headers=auth_headers(USER_A, ORG_A))
        assert click_filter.status_code == 422

        # Mismatched X-Reports-Workspace header returns 409.
        mismatch = await client.get(
            "/api/reports/connectors",
            headers={**auth_headers(USER_A, ORG_A), "X-Reports-Workspace": ORG_B},
        )
        assert mismatch.status_code == 409

        # Connectors endpoint returns all 6 connectors with accurate statuses.
        connectors_a = await client.get("/api/reports/connectors", headers=auth_headers(USER_A, ORG_A))
        assert connectors_a.status_code == 200
        by_key = {item["connector_key"]: item for item in connectors_a.json()["connectors"]}
        assert set(by_key.keys()) == {"google_ads", "ga4", "gsc_bigquery", "meta_ads", "whatconverts", "google_sheets"}
        assert by_key["google_ads"]["status"] == "connected"
        assert by_key["whatconverts"]["status"] == "connected"
        assert by_key["meta_ads"]["status"] == "pending"

        # External client role is denied at both the client boundary and router guard (403).
        assert is_client_allowed_route("GET", "/api/reports/summary") is False
        assert is_client_allowed_route("GET", "/api/reports/leads") is False
        assert is_client_allowed_route("POST", "/api/reports/review-docs") is False
        async with sf() as session, session.begin():
            user_b = await session.get(UserRow, USER_B)
            assert user_b is not None
            user_b.system_role = "client"
        denied = await client.get("/api/reports/summary", headers=auth_headers(USER_B, ORG_B))
        assert denied.status_code == 403


@pytest.mark.asyncio
async def test_review_doc_lifecycle_and_cross_workspace_isolation(reports_app):
    app, _sf = reports_app
    headers_a = auth_headers(USER_A, ORG_S)
    headers_c = auth_headers(USER_C, ORG_S)
    headers_b = auth_headers(USER_B, ORG_B)

    async with _http(app) as client:
        # Reject invalid URL and unexpected body fields.
        bad_url = await client.post(
            "/api/reports/review-docs",
            headers=headers_a,
            json={"title": "Invalid Host Report", "doc_url": "https://example.invalid/doc/1", "period_key": "last_30d"},
        )
        assert bad_url.status_code == 422

        extra_field = await client.post(
            "/api/reports/review-docs",
            headers=headers_a,
            json={
                "title": "Monthly Report",
                "doc_url": "https://docs.google.com/document/d/synthetic-doc-001/edit",
                "period_key": "last_30d",
                "workspace_id": ORG_B,
            },
        )
        assert extra_field.status_code == 422

        # Attach Google Doc -> starts in pending_review.
        created = await client.post(
            "/api/reports/review-docs",
            headers=headers_a,
            json={
                "title": "Monthly Performance Report",
                "doc_url": "https://docs.google.com/document/d/synthetic-doc-001/edit",
                "period_key": "last_30d",
            },
        )
        assert created.status_code == 201, created.text
        doc = created.json()
        assert doc["workspace_id"] == ORG_S
        assert doc["status"] == "pending_review"
        assert doc["comments"] == []
        doc_id = doc["id"]

        # Outsider workspace B cannot see or mutate ORG_S's review doc (404).
        list_b = await client.get("/api/reports/review-docs", headers=headers_b)
        assert list_b.status_code == 200
        assert list_b.json()["review_docs"] == []

        patch_b = await client.patch(
            f"/api/reports/review-docs/{doc_id}",
            headers=headers_b,
            json={"status": "approved"},
        )
        assert patch_b.status_code == 404

        # Empty no-op patch is rejected (422).
        empty_patch = await client.patch(f"/api/reports/review-docs/{doc_id}", headers=headers_c, json={})
        assert empty_patch.status_code == 422

        # Teammate in ORG_S requests edits with a timestamped comment.
        needs_edits = await client.patch(
            f"/api/reports/review-docs/{doc_id}",
            headers=headers_c,
            json={"status": "needs_edits", "comment": "Confirm appointment count matches call log."},
        )
        assert needs_edits.status_code == 200, needs_edits.text
        edited = needs_edits.json()
        assert edited["status"] == "needs_edits"
        assert edited["decided_by"] == USER_C
        assert edited["decided_at"] is not None
        assert len(edited["comments"]) == 1
        assert edited["comments"][0]["body"] == "Confirm appointment count matches call log."
        assert edited["comments"][0]["created_at"]

        # Owner in ORG_S approves with a follow-up comment.
        approved = await client.patch(
            f"/api/reports/review-docs/{doc_id}",
            headers=headers_a,
            json={"status": "approved", "comment": "Verified and ready to share."},
        )
        assert approved.status_code == 200
        final_doc = approved.json()
        assert final_doc["status"] == "approved"
        assert final_doc["decided_by"] == USER_A
        assert len(final_doc["comments"]) == 2


@pytest.mark.asyncio
async def test_migration_0055_reports_leads_round_trip(tmp_path):
    db = tmp_path / "reports_migration.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db}")
    cfg = _get_alembic_config(engine)
    expected_tables = {
        "report_connector_bindings",
        "report_lead_records",
        "report_review_docs",
        "report_workspace_settings",
    }
    try:
        await asyncio.to_thread(command.upgrade, cfg, "0054_no_phi_flag")
        async with engine.connect() as conn:
            before_tables = await conn.run_sync(lambda sync_conn: set(sa_inspect(sync_conn).get_table_names()))
        assert not (expected_tables & before_tables)

        await asyncio.to_thread(command.upgrade, cfg, "0055_reports_leads")
        async with engine.connect() as conn:
            after_tables = await conn.run_sync(lambda sync_conn: set(sa_inspect(sync_conn).get_table_names()))
        assert expected_tables.issubset(after_tables)

        await asyncio.to_thread(command.downgrade, cfg, "0054_no_phi_flag")
        async with engine.connect() as conn:
            rolled_back_tables = await conn.run_sync(lambda sync_conn: set(sa_inspect(sync_conn).get_table_names()))
        assert not (expected_tables & rolled_back_tables)

        await asyncio.to_thread(command.upgrade, cfg, "head")
        async with engine.connect() as conn:
            final_tables = await conn.run_sync(lambda sync_conn: set(sa_inspect(sync_conn).get_table_names()))
        assert expected_tables.issubset(final_tables)
    finally:
        await engine.dispose()
