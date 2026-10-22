"""Operator-mounted per-person profiles used to pre-fill a staff member's onboarding.

``MOMO_PEOPLE_DIR`` points at a read-only folder of ``<email>.md`` files that an
operator builds outside the repository (none of that content belongs in Git).
Each file is optional front matter plus a short body:

    ---
    role: Account manager
    team: Paid media
    clients: Example Co, Sample LLC
    tools: slack, gmail, google_ads
    ---
    Prefers short bullet updates in the morning.

The lookup key is always the signed-in user's own email, never a request
parameter, so a person can only ever load their own profile.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

PEOPLE_DIR_ENV = "MOMO_PEOPLE_DIR"
_EMAIL = re.compile(r"^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}$")
_MAX_BYTES = 64 * 1024
_MAX_NOTES = 600


@dataclass(frozen=True)
class PersonProfile:
    role: str = ""
    team: str = ""
    clients: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    notes: str = ""


def _split(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def parse_profile(text: str) -> PersonProfile:
    meta: dict[str, str] = {}
    body = text
    if text.startswith("---"):
        head, sep, rest = text[3:].partition("\n---")
        if sep:
            body = rest
            for line in head.splitlines():
                key, colon, value = line.partition(":")
                if colon:
                    meta[key.strip().lower()] = value.strip()
    notes = " ".join(body.split())[:_MAX_NOTES]
    return PersonProfile(
        role=meta.get("role", "")[:120],
        team=meta.get("team", "")[:120],
        clients=_split(meta.get("clients", ""))[:30],
        tools=[tool.lower() for tool in _split(meta.get("tools", ""))][:20],
        notes=notes,
    )


def load_own_profile(email: str | None) -> PersonProfile | None:
    """Return the profile for exactly this email, or ``None`` when absent or unsafe."""
    root = os.environ.get(PEOPLE_DIR_ENV)
    normalized = (email or "").strip().lower()
    if not root or not _EMAIL.match(normalized):
        return None
    base = Path(root).resolve()
    path = (base / f"{normalized}.md").resolve()
    if path.parent != base or not path.is_file():
        return None
    try:
        if path.stat().st_size > _MAX_BYTES:
            return None
        return parse_profile(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return None
