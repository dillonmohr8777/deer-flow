"""The weekly client reports pipeline ported onto the harness (dry run)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from deerflow.taskharness import FakeGate, HarnessError, ReceiptLog, RunOutput, run_task
from deerflow.taskharness.weekly_reports import (
    WIDTHS,
    render_report,
    rendered_figures,
    source_pack_judge,
    weekly_reports_spec,
    weekly_reports_worker,
)

FIGURES = {"ga4_sessions": 4821, "gsc_clicks": 612, "meta_spend_usd": 0, "gbp_calls": None}
WEEK = "2026-09-28..2026-10-04"


@pytest.fixture
def pack(tmp_path) -> Path:
    path = tmp_path / "bar-crawl-usa.json"
    path.write_text(json.dumps({"client": "bar-crawl-usa", "week": WEEK, "figures": FIGURES}, sort_keys=True), encoding="utf-8")
    return path


def measuring_probe(_report: Path, width: int) -> dict[str, Any]:
    return {"width": width, "measured": True, "horizontal_overflow": False, "probe": "test_double"}


def dry_spec(pack: Path, tmp_path: Path, **kwargs):
    return weekly_reports_spec(
        "bar-crawl-usa",
        source_pack=pack,
        out_dir=tmp_path / "out",
        week=WEEK,
        judge=source_pack_judge(pack),
        **kwargs,
    )


def test_the_dry_run_is_accepted_and_the_receipt_says_what_happened(pack, tmp_path):
    log = ReceiptLog(tmp_path / "receipts.jsonl")
    spec = dry_spec(pack, tmp_path)
    receipt = run_task(spec, weekly_reports_worker(qa_probe=measuring_probe), receipts=log)

    assert receipt.ok is True
    assert receipt.layer == "accepted"  # not "billed": a dry run spends nothing
    assert (receipt.cost_micro, receipt.attempts, receipt.route) == (0, 1, "local")
    assert [c.name for c in receipt.checks if not c.ok] == []
    assert {c.layer for c in receipt.checks} == {"tested", "accepted"}
    assert len(receipt.evidence) == 3 + len(WIDTHS)  # report + 3 QA files + deploy + post

    out = tmp_path / "out"
    assert json.loads((out / "deploy.json").read_text(encoding="utf-8"))["performed"] is False
    assert json.loads((out / "post.json").read_text(encoding="utf-8"))["performed"] is False
    assert rendered_figures((out / "report.html").read_text(encoding="utf-8")) == FIGURES


def test_a_missing_figure_is_unavailable_and_never_zero(pack, tmp_path):
    run_task(dry_spec(pack, tmp_path), weekly_reports_worker(qa_probe=measuring_probe), receipts=ReceiptLog(tmp_path / "r.jsonl"))
    report = (tmp_path / "out" / "report.html").read_text(encoding="utf-8")
    assert "<th scope='row'>gbp_calls</th><td>unavailable</td>" in report
    assert "<th scope='row'>meta_spend_usd</th><td>0</td>" in report  # a real zero stays zero


def test_qa_fails_closed_when_no_probe_measured_the_three_widths(pack, tmp_path):
    receipt = run_task(dry_spec(pack, tmp_path, max_retries=0), weekly_reports_worker(), receipts=ReceiptLog(tmp_path / "r.jsonl"))
    assert receipt.ok is False
    assert receipt.layer == "prepared"
    qa = next(c for c in receipt.checks if c.name == "qa-390-768-1440")
    assert (qa.ok, "not_measured" in qa.detail) == (False, True)


def test_horizontal_overflow_at_one_width_fails_the_run(pack, tmp_path):
    def overflowing(_report: Path, width: int) -> dict[str, Any]:
        return {"width": width, "measured": True, "horizontal_overflow": width == 390}

    receipt = run_task(dry_spec(pack, tmp_path, max_retries=0), weekly_reports_worker(qa_probe=overflowing), receipts=ReceiptLog(tmp_path / "r.jsonl"))
    assert receipt.ok is False
    assert "qa_390_horizontal_overflow" in next(c.detail for c in receipt.checks if c.name == "qa-390-768-1440")


def test_the_judge_refutes_a_report_whose_tests_are_green_but_whose_figures_are_invented(pack, tmp_path):
    """Structured output matches the pack; the rendered HTML does not."""
    out_dir = tmp_path / "out"
    honest = weekly_reports_worker(qa_probe=measuring_probe)

    def lying_worker(spec, attempt):
        result = honest(spec, attempt)
        # Same output dict (so every deterministic check still passes), but the
        # artifact a human would read now carries a made-up number.
        render_report(out_dir / "report.html", client_id=spec.client_id, week=WEEK, figures={**FIGURES, "gbp_calls": 99})
        return result

    receipt = run_task(dry_spec(pack, tmp_path, max_retries=0), lying_worker, receipts=ReceiptLog(tmp_path / "r.jsonl"))
    assert [c.name for c in receipt.checks if not c.ok] == ["intent-refutation"]
    assert receipt.layer == "tested"
    assert receipt.ok is False
    assert "not in the source pack" in next(c.detail for c in receipt.checks if c.name == "intent-refutation")


def test_a_worker_that_reports_figures_not_in_the_pack_fails_the_deterministic_check(pack, tmp_path):
    def inventing_worker(spec, attempt):
        output = weekly_reports_worker(qa_probe=measuring_probe)(spec, attempt)
        return RunOutput(output={**output.output, "figures": {**FIGURES, "gbp_calls": 0}}, evidence=output.evidence)

    receipt = run_task(dry_spec(pack, tmp_path, max_retries=0), inventing_worker, receipts=ReceiptLog(tmp_path / "r.jsonl"))
    failed = next(c for c in receipt.checks if c.name == "figures-traceable")
    assert failed.ok is False
    assert "not_from_source_pack" in failed.detail or "missing_reported_as_zero" in failed.detail


def test_another_clients_source_pack_is_refused(pack, tmp_path):
    other = tmp_path / "omega.json"
    other.write_text(json.dumps({"client": "omega-landscape", "week": WEEK, "figures": FIGURES}), encoding="utf-8")
    spec = weekly_reports_spec("bar-crawl-usa", source_pack=other, out_dir=tmp_path / "out", week=WEEK, judge=source_pack_judge(other), max_retries=0)
    receipt = run_task(spec, weekly_reports_worker(qa_probe=measuring_probe), receipts=ReceiptLog(tmp_path / "r.jsonl"))
    assert receipt.ok is False
    assert "source_pack_client_mismatch" in receipt.reason


def test_a_live_run_without_injected_callables_cannot_deploy_or_post(pack, tmp_path):
    spec = weekly_reports_spec(
        "bar-crawl-usa",
        source_pack=pack,
        out_dir=tmp_path / "out",
        week=WEEK,
        judge=source_pack_judge(pack),
        dry_run=False,
        deployed_url="https://reports.example.test/bar-crawl-usa",
        http_fetch=lambda _u, _t: 200,
        max_retries=0,
    )
    receipt = run_task(spec, weekly_reports_worker(qa_probe=measuring_probe), receipts=ReceiptLog(tmp_path / "r.jsonl"))
    assert receipt.ok is False
    assert "live_run_requires_deploy_and_post_callables" in receipt.reason


def test_a_live_spec_claims_the_installed_layer(pack, tmp_path):
    spec = weekly_reports_spec(
        "bar-crawl-usa",
        source_pack=pack,
        out_dir=tmp_path / "out",
        week=WEEK,
        judge=source_pack_judge(pack),
        dry_run=False,
        deployed_url="https://reports.example.test/bar-crawl-usa",
        http_fetch=lambda _u, _t: 200,
        route="openrouter",
        cap_micro=2_000,
        max_retries=0,
    )
    worker = weekly_reports_worker(
        qa_probe=measuring_probe,
        deploy=lambda _r: {"performed": True, "url": "https://reports.example.test/bar-crawl-usa"},
        post=lambda _r: {"performed": True, "channel": "#momentum-reports"},
    )
    receipt = run_task(spec, worker, receipts=ReceiptLog(tmp_path / "r.jsonl"), gate=FakeGate())
    assert receipt.ok is True
    assert receipt.layer == "accepted"  # cost settled at 0, so not "billed"
    assert {c.layer for c in receipt.checks} == {"tested", "installed", "accepted"}
    assert "Deploy" in spec.allowed_tools


def test_a_live_spec_needs_a_url_to_check():
    with pytest.raises(HarnessError, match="live_run_requires_deployed_url"):
        weekly_reports_spec("bar-crawl-usa", source_pack="x.json", out_dir=".", week=WEEK, judge=lambda _p: {}, dry_run=False)


def test_a_missing_source_pack_fails_the_run_rather_than_inventing_zeros(tmp_path):
    spec = weekly_reports_spec("bar-crawl-usa", source_pack=tmp_path / "gone.json", out_dir=tmp_path / "out", week=WEEK, judge=lambda _p: {"verdict": "upheld"}, max_retries=0)
    receipt = run_task(spec, weekly_reports_worker(qa_probe=measuring_probe), receipts=ReceiptLog(tmp_path / "r.jsonl"))
    assert receipt.ok is False
    assert "source_pack_unreadable" in receipt.reason


def test_the_second_week_is_a_different_unit_of_work(pack, tmp_path):
    a = dry_spec(pack, tmp_path)
    b = weekly_reports_spec("bar-crawl-usa", source_pack=pack, out_dir=tmp_path / "out", week="2026-10-05..2026-10-11", judge=source_pack_judge(pack))
    assert a.run_key != b.run_key
