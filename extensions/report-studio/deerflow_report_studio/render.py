"""Settings, page rendering and the ``build_report_page`` agent tool. No network, no generated art."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any

from langchain.tools import tool

CLIENT_ID_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
WEEK_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
LOGO_EXTS = ("svg", "png", "webp", "jpg", "jpeg")


@dataclass(frozen=True)
class Settings:
    staging_dir: Path
    assets_dir: Path  # existing logo files named <client_id>.<ext>
    site_id: str
    site_url: str
    token_env: str = "NETLIFY_AUTH_TOKEN"

    @classmethod
    def from_config(cls, config: Any) -> Settings:
        return cls(
            staging_dir=Path(config["staging_dir"]),
            assets_dir=Path(config["assets_dir"]),
            site_id=str(config["site_id"]),
            site_url=str(config["site_url"]).rstrip("/"),
            token_env=str(config.get("token_env", "NETLIFY_AUTH_TOKEN")),
        )


_settings: Settings | None = None


def configure(settings: Settings | None) -> None:
    global _settings
    _settings = settings


def clean(value: Any) -> str:
    """Escape and drop em/en dashes, matching the existing report copy rule."""
    return escape(str(value).replace("—", ", ").replace("–", " to "))


CSS = """:root{--ink:#14181b;--paper:#fff;--muted:#555d63;--line:#d9dde0}*{box-sizing:border-box}body{margin:0;font:16px/1.6 system-ui,sans-serif;color:var(--ink);background:var(--paper)}
.container{max-width:960px;margin:0 auto;padding-inline:22px}.skip-link{position:absolute;left:-999px}.skip-link:focus{left:8px;top:8px}
.logo-stage{display:grid;place-items:center;min-height:320px;padding:48px 22px;margin:0}.hero-mark{max-width:min(420px,66vw);max-height:230px;height:auto;animation:brand-float 6s cubic-bezier(.34,.06,.28,1) infinite}
@keyframes brand-float{0%,20%,64%,100%{transform:translateY(0) scale(1)}32%{transform:translateY(-12px) scale(1.015)}44%{transform:translateY(0) scale(1)}53%{transform:translateY(-5px) scale(1.008)}}
.report-section{padding-block:40px;border-top:1px solid var(--line)}h1,h2{line-height:1.2}.metrics-strip{display:flex;flex-wrap:wrap;gap:24px}.metrics-strip div{min-width:140px}
.metric-number{display:block;font-size:28px;font-weight:700}.metric-label{color:var(--muted);font-size:14px}
@media(prefers-reduced-motion:reduce){.hero-mark{animation:none}}"""


def _section(sec: dict[str, Any]) -> str:
    out = [f"<h2>{clean(sec.get('heading', ''))}</h2>"]
    if sec.get("body"):
        out.append(f"<p>{clean(sec['body'])}</p>")
    if sec.get("metrics"):
        cells = "".join(f'<div><strong class="metric-number">{clean(m["value"])}</strong><span class="metric-label">{clean(m["label"])}</span></div>' for m in sec["metrics"])
        out.append(f'<div class="metrics-strip">{cells}</div>')
    if sec.get("items"):
        out.append("<ul>" + "".join(f"<li>{clean(i)}</li>" for i in sec["items"]) + "</ul>")
    return '<section class="report-section"><div class="container">' + "".join(out) + "</div></section>"


def render_page(*, name: str, week: str, sections: list[dict[str, Any]], logo_file: str) -> str:
    """Render one client's page. Only the passed-in values appear."""
    logo = f"../../assets/{clean(logo_file)}"
    body = "".join(_section(s) for s in sections)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow,noarchive">
<meta name="referrer" content="no-referrer"><title>{clean(name)} weekly report, week of {clean(week)}</title><style>{CSS}</style></head>
<body><a class="skip-link" href="#report">Skip to report</a>
<main><section class="report-cover"><figure class="logo-stage"><img class="hero-mark" src="{logo}" alt="{clean(name)} logo"><figcaption>Week of {clean(week)}</figcaption></figure></section>
<div id="report">{body}</div></main></body></html>
"""


def find_logo(assets_dir: Path, client_id: str) -> Path:
    for ext in LOGO_EXTS:
        path = assets_dir / f"{client_id}.{ext}"
        if path.is_file():
            return path
    raise FileNotFoundError(f"No existing logo asset for {client_id}; add it to the assets folder. A logo is never generated.")


def stage_dir(settings: Settings, client_id: str, week: str) -> Path:
    return settings.staging_dir / client_id / week


def load_staged(settings: Settings, client_id: str, week: str) -> dict[str, bytes]:
    """The staged site files keyed by deploy path, e.g. ``/reports/<id>/index.html``."""
    root = stage_dir(settings, client_id, week)
    return {"/" + p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def bundle_sha256(files: dict[str, bytes]) -> str:
    h = hashlib.sha256()
    for path in sorted(files):
        h.update(path.encode() + b"\0" + hashlib.sha256(files[path]).digest())
    return h.hexdigest()


def build(settings: Settings, client_id: str, week: str, sections: list[dict[str, Any]], client_name: str = "") -> dict[str, Any]:
    if not CLIENT_ID_RE.fullmatch(client_id) or not WEEK_RE.fullmatch(week):
        raise ValueError("client_id must be a lowercase slug and week must be YYYY-MM-DD")
    if not sections:
        raise ValueError("sections is empty; pass the real data to show")
    logo = find_logo(settings.assets_dir, client_id)
    root = stage_dir(settings, client_id, week)
    page = root / "reports" / client_id / "index.html"
    page.parent.mkdir(parents=True, exist_ok=True)
    (root / "assets").mkdir(exist_ok=True)
    page.write_text(render_page(name=client_name or client_id, week=week, sections=sections, logo_file=logo.name), encoding="utf-8")
    (root / "assets" / logo.name).write_bytes(logo.read_bytes())
    files = load_staged(settings, client_id, week)
    return {"staging_path": str(root), "files": sorted(files), "bundle_sha256": bundle_sha256(files)}


@tool(parse_docstring=True)
def build_report_page(client_id: str, week: str, sections: list[dict[str, Any]], client_name: str = "") -> str:
    """Render one client's weekly report page into the staging folder. Never deploys.

    Uses only the data you pass in and the client's existing logo asset. Afterwards call
    propose_action with action_type "deploy_report", target = client_id and
    payload = {"week": week, "bundle_sha256": <value returned here>}.

    Args:
        client_id: Lowercase client slug, for example "acme-roofing".
        week: Week start date as YYYY-MM-DD.
        sections: Real data only. Each item: {"heading": str, "body": str optional, "metrics": [{"label": str, "value": str}] optional, "items": [str] optional}.
        client_name: Display name for the page title and logo alt text. Defaults to client_id.
    """
    if _settings is None:
        return "Report Studio is not configured (plugin not installed)."
    try:
        return json.dumps(build(_settings, client_id, week, sections, client_name))
    except (ValueError, FileNotFoundError, KeyError, TypeError) as exc:
        return f"Not built: {exc}"
