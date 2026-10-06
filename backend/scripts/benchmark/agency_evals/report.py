"""Static HTML report from one or more eval results JSON files (weekly trend plus latest detail)."""

from __future__ import annotations

import json
from html import escape
from pathlib import Path

RAINBOW = ["#ff3b5c", "#ff9f1c", "#ffd60a", "#2ec27e", "#1fb6ff", "#7a5cff"]
CSS = """
body{font:15px/1.5 system-ui,sans-serif;margin:0;padding:24px 16px;background:#fff;color:#14141f;max-width:1000px;margin-inline:auto}
@media(prefers-color-scheme:dark){body{background:#14141f;color:#f4f4f8}th{background:#22222f}td,th{border-color:#33334a}}
h1{font-size:2rem;margin:0 0 4px;background:linear-gradient(90deg,#ff3b5c,#ff9f1c,#e6b800,#2ec27e,#1fb6ff,#7a5cff);-webkit-background-clip:text;background-clip:text;color:transparent}
h2{margin-top:32px;border-bottom:4px solid;border-image:linear-gradient(90deg,#ff3b5c,#ff9f1c,#ffd60a,#2ec27e,#1fb6ff,#7a5cff) 1;padding-bottom:4px}
.wrap{overflow-x:auto}table{border-collapse:collapse;width:100%}td,th{border:1px solid #d8d8e4;padding:6px 10px;text-align:left;vertical-align:top}th{background:#f1f1f7}
.pass{color:#117a46;font-weight:700}.fail{color:#c4143a;font-weight:700}.bar{display:inline-block;height:12px;border-radius:6px;vertical-align:middle}
.big{font-size:1.6rem;font-weight:800}.cards{display:flex;gap:12px;flex-wrap:wrap}.card{flex:1 1 140px;border:2px solid;border-radius:10px;padding:10px 14px}
details{margin:4px 0}pre{white-space:pre-wrap;background:#00000012;padding:8px;border-radius:6px}
"""


def _bar(rate: float, color: str) -> str:
    return f'<span class="bar" style="width:{max(2, round(rate * 120))}px;background:{color}"></span>'


def render(docs: list[dict]) -> str:
    latest = docs[-1]
    t = latest["totals"]
    parts = [f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>Agency evals</title><style>{CSS}</style>"]
    parts.append(f"<h1>Agency evals</h1><div>{escape(latest['model'])} &middot; {escape(latest['started_at'])}</div>")
    cards = [("Pass rate", f"{t['pass_rate']:.0%}"), ("Passed", f"{t['passed']}/{t['tasks']}"), ("Cost per task", f"${t['cost_per_task']:.4f}"), ("Total cost", f"${t['cost']:.4f}"), ("Errors", str(t["errors"]))]
    parts.append('<div class="cards">' + "".join(f'<div class="card" style="border-color:{RAINBOW[i]}"><div>{k}</div><div class="big">{v}</div></div>' for i, (k, v) in enumerate(cards)) + "</div>")
    parts.append('<h2>Weekly trend</h2><div class="wrap"><table><tr><th>Run</th><th>Model</th><th>Pass rate</th><th>Cost per task</th><th>Tasks</th></tr>')
    for i, d in enumerate(docs):
        x = d["totals"]
        parts.append(f"<tr><td>{escape(d['started_at'])}</td><td>{escape(d['model'])}</td><td>{_bar(x['pass_rate'], RAINBOW[i % 6])} <b>{x['pass_rate']:.0%}</b></td><td>${x['cost_per_task']:.4f}</td><td>{x['tasks']}</td></tr>")
    parts.append("</table></div><h2>By category (latest)</h2><div class='wrap'><table><tr><th>Category</th><th>Pass rate</th><th>Passed</th><th>Cost</th></tr>")
    for i, (cat, c) in enumerate(sorted(t["by_category"].items())):
        parts.append(f"<tr><td>{escape(cat)}</td><td>{_bar(c['pass_rate'], RAINBOW[i % 6])} <b>{c['pass_rate']:.0%}</b></td><td>{c['passed']}/{c['n']}</td><td>${c['cost']:.4f}</td></tr>")
    parts.append("</table></div><h2>Tasks (latest)</h2>")
    for r in latest["results"]:
        mark = '<span class="pass">PASS</span>' if r["passed"] else '<span class="fail">FAIL</span>'
        failed = "; ".join(f"{c['name']}: {c['detail']}" for c in r["checks"] if not c["passed"]) or r.get("error", "")
        parts.append(f"<details><summary>{mark} <b>{escape(r['id'])}</b> ({escape(r['category'])}) {escape(failed)}</summary><pre>{escape(r.get('output', ''))}</pre></details>")
    return "".join(parts)


def build_report(paths: list[Path], out: Path) -> None:
    docs = [json.loads(Path(p).read_text(encoding="utf-8")) for p in paths]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(docs), encoding="utf-8")
