"""Reader for the private MomoBot brand kit (About copy, Agents lineup, assets).

The kit lives in a server-side folder named by ``momobot_brand.content_dir`` and
is never committed. Prices leave this module only when agents.json says
``show_pricing: true``; internal notes never leave it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

KIT_FILE = "agents.json"
ABOUT_FILE = "about.md"
ASSET_DIRS = frozenset({"icons", "mascot", "videos", "stills", "fonts"})
PRICING_MARKER = "<!--pricing-->"
NOT_CONFIGURED_REPLY = "About MomoBot is not set up on this workspace yet."

_INTERNAL_KEYS = frozenset({"pricing_status", "system", "icon_style"})
_DOLLAR = re.compile(r"\$\s?\d")


def configured_content_dir() -> Path | None:
    from deerflow.config.app_config import get_app_config

    raw = get_app_config().momobot_brand.content_dir
    return Path(raw).expanduser() if raw else None


def _scrub(node: Any, show_pricing: bool) -> Any:
    if isinstance(node, dict):
        return {k: _scrub(v, show_pricing) for k, v in node.items() if k not in _INTERNAL_KEYS and (k != "price" or show_pricing)}
    if isinstance(node, list):
        return [_scrub(v, show_pricing) for v in node]
    return node


def load_kit(content_dir: Path) -> dict[str, Any]:
    """Return agents.json with prices removed unless the file says to show them."""
    kit = json.loads((content_dir / KIT_FILE).read_text(encoding="utf-8"))
    show = kit.get("show_pricing") is True
    out = _scrub(kit, show)
    out["show_pricing"] = show
    return out


def load_about(content_dir: Path) -> str:
    """About copy as markdown; price paragraphs are dropped unless pricing is shown."""
    show = load_kit(content_dir)["show_pricing"]
    kept = []
    for block in (content_dir / ABOUT_FILE).read_text(encoding="utf-8").split("\n\n"):
        priced = PRICING_MARKER in block or bool(_DOLLAR.search(block))
        if show or not priced:
            kept.append(block.replace(PRICING_MARKER, "").strip())
    return "\n\n".join(b for b in kept if b)


def about_reply(content_dir: Path | None) -> str:
    """Slack reply for ``/momobot about``; never raises."""
    if content_dir is None:
        return NOT_CONFIGURED_REPLY
    try:
        return load_about(content_dir) or NOT_CONFIGURED_REPLY
    except (OSError, ValueError):
        return NOT_CONFIGURED_REPLY


def resolve_asset(content_dir: Path, rel: str) -> Path | None:
    """Map a request path to a kit file, or None if it escapes the allowed folders."""
    parts = Path(rel).parts
    if not parts or parts[0] not in ASSET_DIRS or ".." in parts:
        return None
    root = content_dir.resolve()
    target = (root / rel).resolve()
    return target if target.is_relative_to(root) and target.is_file() else None
