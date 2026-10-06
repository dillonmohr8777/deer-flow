"""Offline tests for the read-only ads tools (mocked HTTP; no live calls)."""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from deerflow.community.ads import derive, google, meta
from deerflow.community.ads.common import AdsToolError
from deerflow.config import paths as paths_module
from deerflow.config.paths import Paths

SECRET = "s3cr3t-refresh-token"
CREDS = {
    "google_ads": {"client_id": "cid", "client_secret": "csec", "refresh_token": SECRET, "login_customer_id": "703-843-3673", "allowed_customer_ids": ["123-456-7890"]},
    "meta_ads": {"access_token": "meta-secret-token", "allowed_account_ids": ["act_555"]},
}


@pytest.fixture(autouse=True)
def user_creds(tmp_path, monkeypatch):
    monkeypatch.setattr(paths_module, "_paths", Paths(base_dir=tmp_path))
    d = tmp_path / "users" / "test-user-autouse" / "integrations" / "ads"
    d.mkdir(parents=True)
    (d / "credentials.json").write_text(json.dumps(CREDS))


def _resp(payload, status=200):
    r = MagicMock(status_code=status, headers={"content-type": "application/json"})
    r.json.return_value = payload
    return r


# --- GAQL guard -------------------------------------------------------------


@pytest.mark.parametrize(
    "q",
    [
        "SELECT campaign.id FROM campaign; SELECT 1 FROM customer",
        "UPDATE campaign SET status = 'PAUSED'",
        "SELECT campaign.id FROM campaign_budget",
        "SELECT campaign.id FROM campaign WHERE campaign.name = 'x' AND remove = 1",
        "SELECT campaign.id FROM campaign LIMIT 5000",
        "SELECT campaign.id FROM campaign, ad_group",
    ],
)
def test_gaql_rejects_unsafe(q):
    with pytest.raises(AdsToolError):
        google.validate_gaql(q)


def test_gaql_allows_field_names_and_literals_containing_keywords():
    q = google.validate_gaql("SELECT campaign.name FROM campaign WHERE campaign.name = 'update set remove'")
    assert q.endswith("LIMIT 1000")
    assert google.validate_gaql("SELECT customer.id FROM customer LIMIT 5").endswith("LIMIT 5")


def test_date_range_injection():
    q = google.apply_date_range("SELECT metrics.clicks FROM campaign WHERE campaign.status = 'ENABLED' LIMIT 9", "2026-01-01", "2026-01-31")
    assert "WHERE segments.date BETWEEN '2026-01-01' AND '2026-01-31' AND campaign.status" in q
    q2 = google.apply_date_range("SELECT metrics.clicks FROM campaign ORDER BY metrics.clicks DESC LIMIT 9", "2026-01-01", "2026-01-31")
    assert q2.index("WHERE") < q2.index("ORDER BY")
    with pytest.raises(AdsToolError):
        google.apply_date_range("SELECT 1 FROM customer", "2026-02-01", "2026-01-01")


# --- Google tool ------------------------------------------------------------

GOOGLE_ROWS = {
    "results": [
        {"segments": {"month": "2026-05-01"}, "metrics": {"costMicros": "1000000000", "conversions": 4, "clicks": "100"}},
        {"segments": {"month": "2026-06-01"}, "metrics": {"costMicros": "1672000000", "conversions": 13, "clicks": "400"}},
        {"segments": {"month": "2026-07-01"}, "metrics": {"costMicros": "50000000", "conversions": 1}},
        {"segments": {"month": "2026-08-01"}, "metrics": {"costMicros": "900000000"}},
    ]
}


def test_google_report_stamp_scoping_and_best_month():
    with patch("deerflow.community.ads.google.httpx.post", side_effect=[_resp({"access_token": "tok"}), _resp(GOOGLE_ROWS)]) as post:
        out = json.loads(google.google_ads_report_tool.invoke({"customer_id": "1234567890", "query": "SELECT segments.month, metrics.cost_micros, metrics.conversions FROM customer", "monthly_summary": True}))
    assert out["source"].startswith("Google Ads API, read ") and out["source"].endswith("customer ******7890")
    call = post.call_args_list[1]
    assert call.args[0].endswith("/customers/1234567890/googleAds:search")
    assert call.kwargs["headers"]["login-customer-id"] == "7038433673"
    assert out["rows"][0]["metrics.cost"] == 1000.0 and "metrics.cost_micros" not in out["rows"][0]
    assert out["best_month"]["month"] == "2026-06"  # $128.62/conv beats May ($250, 4 conv fails volume)
    aug = out["monthly_kpis"][-1]
    assert aug["conversions"] is None and aug["cost_per_conversion"] is None  # missing is unavailable, never 0
    assert SECRET not in json.dumps(out)


def test_google_report_rejects_unlinked_customer_without_http():
    with patch("deerflow.community.ads.google.httpx.post") as post:
        out = json.loads(google.google_ads_report_tool.invoke({"customer_id": "999", "query": "SELECT customer.id FROM customer"}))
    assert "not linked" in out["error"] and not post.called


def test_google_api_error_is_reported_without_secrets():
    with patch("deerflow.community.ads.google.httpx.post", side_effect=[_resp({"access_token": "tok"}), _resp({"error": {"message": "bad field"}}, 400)]):
        out = google.google_ads_report_tool.invoke({"customer_id": "1234567890", "query": "SELECT customer.id FROM customer"})
    assert "bad field" in out and SECRET not in out and "tok" not in json.loads(out)["error"].split()


def test_missing_credentials_file(tmp_path, monkeypatch):
    monkeypatch.setattr(paths_module, "_paths", Paths(base_dir=tmp_path / "empty"))
    out = json.loads(google.google_ads_report_tool.invoke({"customer_id": "1", "query": "SELECT customer.id FROM customer"}))
    assert "No ads credentials" in out["error"]


# --- Meta tool --------------------------------------------------------------

META_PAGE = {
    "data": [
        {
            "campaign_name": "A",
            "date_start": "2026-06-01",
            "spend": "300",
            "impressions": "1000",
            "reach": "800",
            "clicks": "50",
            "actions": [{"action_type": "lead", "value": "10"}, {"action_type": "offsite_conversion.fb_pixel_lead", "value": "10"}],
        },
        {"campaign_name": "A", "date_start": "2026-07-01", "spend": "100", "impressions": "500", "clicks": "9"},
    ]
}


def test_meta_insights_cpl_best_month_and_missing():
    with patch("deerflow.community.ads.meta.httpx.get", return_value=_resp(META_PAGE)) as get:
        out = json.loads(meta.meta_ads_insights_tool.invoke({"account_id": "act_555", "start_date": "2026-06-01", "end_date": "2026-07-31", "monthly": True}))
    assert out["source"].startswith("Meta Marketing API, read ") and out["source"].endswith("account act_555")
    assert get.call_args.kwargs["headers"]["Authorization"] == "Bearer meta-secret-token"
    assert "meta-secret-token" not in json.dumps(out) and "meta-secret-token" not in json.dumps(get.call_args.kwargs["params"])
    assert out["rows"][0]["leads"] == 10.0 and out["rows"][0]["cpl"] == 30.0  # lead not double counted with pixel lead
    assert out["rows"][1]["leads"] is None and out["rows"][1]["cpl"] is None
    assert out["best_month"]["month"] == "2026-06"
    assert out["monthly_kpis"][1]["cpl"] is None


def test_meta_rejects_unlinked_account_and_bad_level():
    with patch("deerflow.community.ads.meta.httpx.get") as get:
        a = json.loads(meta.meta_ads_insights_tool.invoke({"account_id": "777", "start_date": "2026-06-01", "end_date": "2026-06-30"}))
        b = json.loads(meta.meta_ads_insights_tool.invoke({"account_id": "555", "start_date": "2026-06-01", "end_date": "2026-06-30", "level": "ad; DELETE"}))
    assert "not linked" in a["error"] and "level" in b["error"] and not get.called


# --- derive -----------------------------------------------------------------


def test_best_month_unavailable_when_volume_too_low():
    table = derive.monthly_kpis([{"m": "2026-01-01", "s": 100, "c": 2}], "m", "s", "c")
    res = derive.best_month(table)
    assert res["best_month"] is None and "unavailable" in res["note"]


# --- optional live ----------------------------------------------------------


@pytest.mark.live
@pytest.mark.skipif(not os.getenv("DEER_FLOW_ADS_LIVE_GOOGLE_CUSTOMER"), reason="set DEER_FLOW_ADS_LIVE_GOOGLE_CUSTOMER and a real credentials file")
def test_live_google_customer_read():
    paths_module._paths = None  # use the real DEER_FLOW_HOME
    out = json.loads(google.google_ads_report_tool.invoke({"customer_id": os.environ["DEER_FLOW_ADS_LIVE_GOOGLE_CUSTOMER"], "query": "SELECT customer.id, metrics.clicks FROM customer", "start_date": "2026-09-01", "end_date": "2026-09-30"}))
    assert "source" in out, out


def test_credentials_are_per_user():
    with pytest.raises(AdsToolError, match="No ads credentials"):
        google.run_report("1234567890", "SELECT customer.id FROM customer", None, None, False, user_id="someone-else")
