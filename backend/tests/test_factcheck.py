"""verify_claims: deterministic fact-checker for outbound drafts."""

import json
from types import SimpleNamespace

from langchain_core.messages import ToolMessage

from deerflow.factcheck import Evidence, verify_draft
from deerflow.tools.builtins.verify_claims_tool import verify_claims_tool

GOOGLE_TERMS = Evidence("google_ads_search_terms", '{"account": "Omega Landscape", "channel": "Google Ads", "queries": 537, "clicks": 214, "impressions": 6100, "ctr": 3.5}')
SPEND = Evidence("google_ads_report", "Google Ads, Sep 1 - Sep 30: spend $1,240.50, conversions 18, CPA $68.92.")
ROAS = Evidence("meta_ads_report", "Meta Ads\nAug: purchases 80, spend 1000\nSep: purchases 100, spend 1000\nconversions: unavailable")


def verdicts(draft, evidence):
    r = verify_draft(draft, evidence)
    return r, {c.raw: c.verdict for c in r.claims}


def test_reddit_ads_label_on_google_data_is_contradicted_and_blocks():
    r, v = verdicts("We reviewed 537 Reddit Ads queries this month.", [GOOGLE_TERMS])
    assert v["537"] == "contradicted"
    assert r.blocked and r.gate == "block"
    assert "google ads" in r.claims[0].conflicting


def test_scope_with_no_platform_in_evidence_is_flagged_not_supported():
    r, v = verdicts("We reviewed 537 Reddit Ads queries.", [Evidence("export.csv", "queries: 537")])
    assert v["537"] == "unsupported" and r.gate == "flag"


def test_unsourced_ctr_is_unsupported():
    r, v = verdicts("The new ad hit a 55% CTR.", [SPEND])
    assert v["55%"] == "unsupported" and r.gate == "flag"


def test_ctr_that_differs_from_the_source_is_contradicted():
    r, v = verdicts("The new ad hit a 55% CTR.", [GOOGLE_TERMS])
    assert v["55%"] == "contradicted" and r.claims[0].conflicting == "3.5"


def test_clean_draft_passes_with_evidence_pointers():
    draft = "Google Ads spend was $1,240.50 with 18 conversions at a $68.92 CPA. We saw 537 queries and 214 clicks."
    r = verify_draft(draft, [GOOGLE_TERMS, SPEND])
    assert r.gate == "pass", r.to_dict()
    assert all(c.verdict == "supported" and c.evidence for c in r.claims)


def test_missing_data_is_not_zero():
    r, v = verdicts("Meta Ads drove 0 conversions.", [ROAS])
    assert v["0"] == "contradicted" and r.claims[0].conflicting == "unavailable"


def test_improvement_needs_before_after_from_same_source():
    ok = verify_draft("Meta Ads purchases were up 25% in September.", [ROAS])
    assert ok.claims[0].verdict == "supported" and "before 80 -> after 100" in ok.claims[0].evidence
    bare = verify_draft("Purchases were up 25% in September.", [Evidence("note", "Sales team says things are up 25%")])
    assert bare.claims[0].verdict == "unsupported" and "before/after" in bare.claims[0].reason


def test_improvement_with_flipped_direction_is_contradicted():
    r = verify_draft("Meta Ads purchases were down 25% in September.", [ROAS])
    assert r.claims[0].verdict == "contradicted" and r.blocked


def test_dates_and_named_sources():
    r = verify_draft("Per the Search Console export, the audit ran on Sep 30 and again on Oct 9.", [Evidence("search_console_export", "audit ran 2026-09-30")])
    by = {c.raw: c.verdict for c in r.claims}
    assert by["Sep 30"] == "supported" and by["Oct 9"] == "unsupported" and by["Search Console"] == "supported"


def test_rounding_and_ratio_forms_match():
    r = verify_draft("CTR was 3.2% and spend was $1.2k.", [Evidence("r", '{"ctr": 0.032, "spend": 1180}')])
    assert [c.verdict for c in r.claims] == ["supported", "supported"]


def test_ambiguous_value_uses_judge_only_when_given():
    ev = [Evidence("r", "total clicks 214; sessions 9000; 99 other")]
    draft = "We got 99 conversions."
    assert verify_draft(draft, ev).claims[0].verdict == "unverifiable"
    seen = []
    judged = verify_draft(draft, ev, judge=lambda c, s: seen.append((c, s)) or "unsupported")
    assert judged.claims[0].verdict == "unsupported" and seen


def test_tool_harvests_run_tool_outputs_and_extra_evidence():
    runtime = SimpleNamespace(state={"messages": [ToolMessage(GOOGLE_TERMS.text, name="google_ads_search_terms", tool_call_id="1"), ToolMessage("boom 537 Reddit Ads", name="x", tool_call_id="2", status="error")]})
    out = json.loads(verify_claims_tool.func(runtime=runtime, draft="537 Reddit Ads queries"))
    assert out["gate"] == "block"
    out = json.loads(verify_claims_tool.func(runtime=runtime, draft="537 Google Ads queries and 9 leads", evidence=[{"source": "crm", "text": "leads: 9"}]))
    assert out["gate"] == "pass"
