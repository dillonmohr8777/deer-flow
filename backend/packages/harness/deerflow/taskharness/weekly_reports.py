"""The weekly client reports pipeline as a harness spec.

Proof that a real workflow is configuration, not new framework code: build ->
QA at 390/768/1440 -> deploy -> post, expressed as one `TaskSpec` with its own
checks and stop rule. Dry run is the default and the only mode that works
without injected callables, so no deploy and no Slack post can happen here.

Honesty rules baked into the checks, not the prompt:
* a figure missing from the source pack renders as "unavailable", never 0;
* QA counts only if a probe actually measured the three widths;
* the judge reads the rendered report, not the worker's own summary of it, so a
  report whose structured output is right and whose HTML is wrong is refuted.
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .contract import HarnessError, RunOutput, TaskSpec
from .runner import Worker
from .verify import FileExistsCheck, HttpStatusCheck, JudgeCheck, PredicateCheck, SchemaCheck

WIDTHS = (390, 768, 1440)
UNAVAILABLE = "unavailable"
# One row of the rendered report. Read back by `rendered_figures`, which is how
# the judge sees what a human would see rather than what the worker claims.
_ROW_RE = re.compile(r'<th scope="row">(.*?)</th><td>(.*?)</td>')

OUTPUT_FIELDS: Mapping[str, type] = {
    "report": str,
    "artifacts": list,
    "figures": dict,
    "unavailable": list,
    "deploy_performed": bool,
    "post_performed": bool,
    "week": str,
}

QaProbe = Callable[[Path, int], Mapping[str, Any]]


def read_source_pack(path: str | Path) -> dict[str, Any]:
    """Client-scoped figures. A null value means unavailable, never zero."""
    try:
        pack = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HarnessError(f"source_pack_unreadable:{path}") from exc
    if not isinstance(pack, dict) or not isinstance(pack.get("figures"), dict):
        raise HarnessError("source_pack_shape_invalid")
    return pack


def display_value(value: Any) -> str:
    """What the report shows for one figure. Missing is never zero."""
    return UNAVAILABLE if value is None else str(value)


def render_report(path: Path, *, client_id: str, week: str, figures: Mapping[str, Any]) -> None:
    """Write the client-facing report.

    Everything interpolated is HTML-escaped: the figure keys come from a source
    pack file, which is data, not markup.
    """
    rows = "".join(f'<tr><th scope="row">{html.escape(key)}</th><td>{html.escape(display_value(figures[key]))}</td></tr>' for key in sorted(figures))
    title = html.escape(f"Weekly report {client_id} {week}")
    path.write_text(
        f"<!doctype html>\n<title>{title}</title>\n<h1>{title}</h1>\n<table>{rows}</table>\n",
        encoding="utf-8",
    )


def _unmeasured(_report: Path, width: int) -> dict[str, Any]:
    return {"width": width, "measured": False, "reason": "no_qa_probe_injected"}


def weekly_reports_worker(*, qa_probe: QaProbe | None = None, deploy: Callable[[Path], Mapping[str, Any]] | None = None, post: Callable[[Path], Mapping[str, Any]] | None = None) -> Worker:
    """Build the worker. Without a probe, QA fails closed instead of passing."""
    probe = qa_probe or _unmeasured

    def worker(spec: TaskSpec, attempt: int) -> RunOutput:
        out_dir = Path(str(spec.inputs["out_dir"]))
        out_dir.mkdir(parents=True, exist_ok=True)
        dry_run = bool(spec.inputs.get("dry_run", True))
        pack = read_source_pack(spec.inputs["source_pack"])
        if pack.get("client") not in (None, spec.client_id):
            raise HarnessError("source_pack_client_mismatch")
        figures = dict(pack["figures"])
        week = str(spec.inputs.get("week") or pack.get("week") or "")

        report = out_dir / "report.html"
        render_report(report, client_id=spec.client_id, week=week, figures=figures)

        artifacts = [str(report)]
        for width in WIDTHS:
            observation = dict(probe(report, width))
            observation.setdefault("width", width)
            qa_path = out_dir / f"qa-{width}.json"
            qa_path.write_text(json.dumps(observation, sort_keys=True), encoding="utf-8")
            artifacts.append(str(qa_path))

        if dry_run:
            deploy_record: Mapping[str, Any] = {"performed": False, "mode": "dry_run", "target": spec.inputs.get("deployed_url", "")}
            post_record: Mapping[str, Any] = {"performed": False, "mode": "dry_run", "channel": spec.inputs.get("post_channel", "")}
        else:
            if deploy is None or post is None:
                raise HarnessError("live_run_requires_deploy_and_post_callables")
            deploy_record = dict(deploy(report))
            post_record = dict(post(report))

        for name, record in (("deploy.json", deploy_record), ("post.json", post_record)):
            path = out_dir / name
            path.write_text(json.dumps(dict(record), sort_keys=True), encoding="utf-8")
            artifacts.append(str(path))

        return RunOutput(
            output={
                "report": str(report),
                "artifacts": artifacts,
                "figures": figures,
                "unavailable": sorted(k for k, v in figures.items() if v is None),
                "deploy_performed": bool(deploy_record.get("performed")),
                "post_performed": bool(post_record.get("performed")),
                "week": week,
            },
            evidence=tuple(artifacts),
            model="",
            done=True,  # advisory only; the checks decide
        )

    return worker


def _figures_traceable(spec: TaskSpec, output: RunOutput) -> tuple[bool, str]:
    pack = read_source_pack(spec.inputs["source_pack"])
    source = pack["figures"]
    reported = output.output.get("figures", {})
    if set(reported) != set(source):
        return False, f"figure_set_mismatch: {sorted(set(reported) ^ set(source))}"
    invented = [k for k, v in reported.items() if v != source[k]]
    if invented:
        return False, f"not_from_source_pack: {sorted(invented)}"
    expected_unavailable = sorted(k for k, v in source.items() if v is None)
    if sorted(output.output.get("unavailable", [])) != expected_unavailable:
        return False, f"unavailable_mismatch: expected {expected_unavailable}"
    zeroed = [k for k in expected_unavailable if reported[k] == 0]
    if zeroed:
        return False, f"missing_reported_as_zero: {zeroed}"
    return True, f"{len(source)} figures traced, {len(expected_unavailable)} unavailable"


def _qa_widths(spec: TaskSpec, output: RunOutput) -> tuple[bool, str]:
    out_dir = Path(str(spec.inputs["out_dir"]))
    for width in WIDTHS:
        path = out_dir / f"qa-{width}.json"
        try:
            observation = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return False, f"qa_{width}_unreadable: {exc}"
        if observation.get("width") != width:
            return False, f"qa_{width}_width_mismatch"
        if not observation.get("measured"):
            return False, f"qa_{width}_not_measured: {observation.get('reason', '')}"
        if observation.get("horizontal_overflow"):
            return False, f"qa_{width}_horizontal_overflow"
    return True, f"measured at {', '.join(str(w) for w in WIDTHS)}"


def _no_side_effects(spec: TaskSpec, output: RunOutput) -> tuple[bool, str]:
    if output.output.get("deploy_performed") or output.output.get("post_performed"):
        return False, "dry_run_violated: deploy or post performed"
    return True, "no deploy, no post"


def _side_effects_done(spec: TaskSpec, output: RunOutput) -> tuple[bool, str]:
    if not output.output.get("deploy_performed"):
        return False, "deploy_not_performed"
    if not output.output.get("post_performed"):
        return False, "post_not_performed"
    return True, "deployed and posted"


def rendered_figures(report_text: str) -> dict[str, str]:
    """What the rendered report actually displays, key -> shown value."""
    return {html.unescape(key): html.unescape(value) for key, value in _ROW_RE.findall(report_text)}


def source_pack_judge(source_pack: str | Path) -> Callable[[str], dict[str, Any]]:
    """A judge DOUBLE: deterministic, offline, no model call and no spend.

    It does what a judge model is asked to do -- read the rendered evidence in
    the prompt and try to refute the result -- by comparing the report's own
    figures block against the client's source pack. Swap in a real model call
    with the same `(prompt) -> {"verdict", "why"}` contract when a paid route is
    approved; nothing else in the spec changes.
    """

    def judge(prompt: str) -> dict[str, Any]:
        source = read_source_pack(source_pack)["figures"]
        shown = rendered_figures(prompt)
        if not shown:
            return {"verdict": "refuted", "why": "the report shows no figures at all"}
        if set(shown) != set(source):
            return {"verdict": "refuted", "why": f"rendered figures do not match the source pack keys: {sorted(set(shown) ^ set(source))}"}
        wrong = sorted(key for key, value in shown.items() if value != display_value(source[key]))
        if wrong:
            return {"verdict": "refuted", "why": f"the rendered report shows figures that are not in the source pack: {wrong}"}
        return {"verdict": "upheld", "why": "every rendered figure traces to the client source pack"}

    return judge


def weekly_reports_spec(
    client_id: str,
    *,
    source_pack: str | Path,
    out_dir: str | Path,
    week: str,
    judge: Callable[[str], Mapping[str, Any]],
    dry_run: bool = True,
    deployed_url: str = "",
    post_channel: str = "",
    route: str = "local",
    cap_micro: int = 0,
    max_retries: int = 1,
    http_fetch: Callable[[str, float], int] | None = None,
) -> TaskSpec:
    """The whole workflow, in one spec. Dry run claims no `installed` layer."""
    checks: list[Any] = [
        SchemaCheck("output-shape", OUTPUT_FIELDS, layer="tested"),
        FileExistsCheck("artifacts-on-disk", output_key="artifacts", layer="tested"),
        PredicateCheck("figures-traceable", _figures_traceable, layer="tested"),
        PredicateCheck("qa-390-768-1440", _qa_widths, layer="tested"),
    ]
    if dry_run:
        checks.append(PredicateCheck("no-deploy-no-post", _no_side_effects, layer="tested"))
        stop_rule = "Stop when the figures trace to the client source pack, QA measured 390/768/1440 with no overflow, nothing was deployed or posted, and the judge cannot refute the rendered report."
    else:
        if not deployed_url:
            raise HarnessError("live_run_requires_deployed_url")
        checks.append(PredicateCheck("deploy-and-post-done", _side_effects_done, layer="installed"))
        checks.append(HttpStatusCheck("deployed-url-200", deployed_url, layer="installed", fetch=http_fetch))
        stop_rule = "Stop when the figures trace to the source pack, QA measured 390/768/1440, the deployed URL returns 200, the post receipt exists, and the judge cannot refute the rendered report."
    checks.append(JudgeCheck("intent-refutation", judge, layer="accepted"))

    return TaskSpec(
        id=f"weekly-report:{client_id}:{week}",
        client_id=client_id,
        goal=f"Build, QA and ship the {week} weekly report for {client_id} from its own source pack only.",
        inputs={
            "source_pack": str(source_pack),
            "out_dir": str(out_dir),
            "week": week,
            "dry_run": dry_run,
            "deployed_url": deployed_url,
            "post_channel": post_channel,
        },
        allowed_tools=("Read", "Write", "Glob", "Grep") if dry_run else ("Read", "Write", "Glob", "Grep", "Deploy", "Post"),
        route=route,
        cap_micro=cap_micro,
        stop_rule=stop_rule,
        checks=tuple(checks),
        data_class="client_private",
        max_retries=max_retries,
        escalate_to="dillon",
    )


def _demo() -> int:
    """Dry run end to end in a temp dir; prints the receipt it earns."""
    import tempfile  # noqa: PLC0415 - demo only

    from .contract import ReceiptLog  # noqa: PLC0415
    from .runner import run_task  # noqa: PLC0415

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pack = root / "bar-crawl-usa-20260928.json"
        pack.write_text(
            json.dumps(
                {
                    "client": "bar-crawl-usa",
                    "week": "2026-09-28..2026-10-04",
                    "figures": {"ga4_sessions": 4821, "gsc_clicks": 612, "meta_spend_usd": 0, "gbp_calls": None},
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )

        def probe(_report: Path, width: int) -> dict[str, Any]:
            # Stand-in for the browser QA pass. Labelled, not pretended.
            return {"width": width, "measured": True, "horizontal_overflow": False, "probe": "demo_double"}

        receipts = ReceiptLog(root / "receipts.jsonl")
        spec = weekly_reports_spec(
            "bar-crawl-usa",
            source_pack=pack,
            out_dir=root / "out",
            week="2026-09-28..2026-10-04",
            judge=source_pack_judge(pack),
        )
        receipt = run_task(spec, weekly_reports_worker(qa_probe=probe), receipts=receipts)
        print(json.dumps(receipt.to_json(), indent=2, sort_keys=True))
        again = run_task(spec, weekly_reports_worker(qa_probe=probe), receipts=receipts)
        print(f"\nre-run returned the same receipt: {again == receipt}; receipts on disk: {len(list(receipts))}")
    return 0 if receipt.ok else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_demo())
