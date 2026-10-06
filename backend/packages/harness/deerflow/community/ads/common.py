"""Shared helpers: per-user credential file, source stamps, date checks."""

import json
import re
from datetime import UTC, date, datetime
from typing import Any

from deerflow.config.paths import get_paths
from deerflow.runtime.user_context import get_effective_user_id

# Per-user file: {base}/users/{user_id}/integrations/ads/credentials.json (chmod 600).
CREDENTIALS_RELPATH = ("integrations", "ads", "credentials.json")


class AdsToolError(Exception):
    """User-presentable failure. Never put secrets in the message."""


def load_credentials(platform: str, user_id: str | None = None) -> dict[str, Any]:
    uid = user_id or get_effective_user_id()
    path = get_paths().user_dir(uid).joinpath(*CREDENTIALS_RELPATH)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise AdsToolError(f"No ads credentials configured for this user ({platform}). See the ads integration setup steps.") from None
    except (OSError, ValueError):
        raise AdsToolError("Ads credentials file is unreadable or not valid JSON.") from None
    section = data.get(platform) if isinstance(data, dict) else None
    if not isinstance(section, dict):
        raise AdsToolError(f"No '{platform}' section in this user's ads credentials.")
    return section


def digits(value: object) -> str:
    return re.sub(r"\D", "", str(value or ""))


def require_allowed(account_id: str, allowed: object, label: str) -> str:
    """Client scoping: only IDs the user's own credentials list are queryable."""
    acct = digits(account_id)
    allowed_ids = {digits(a) for a in allowed} if isinstance(allowed, list) else set()
    if not acct or acct not in allowed_ids:
        raise AdsToolError(f"{label} is not linked to this user. Allowed accounts are set in the user's ads credentials.")
    return acct


def mask(account_id: str) -> str:
    return "*" * max(len(account_id) - 4, 0) + account_id[-4:]


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def check_dates(start_date: str, end_date: str) -> None:
    try:
        start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
    except (TypeError, ValueError):
        raise AdsToolError("start_date and end_date must be ISO dates (YYYY-MM-DD).") from None
    if start > end:
        raise AdsToolError("start_date must be on or before end_date.")


def error_json(exc: Exception) -> str:
    return json.dumps({"error": str(exc) if isinstance(exc, AdsToolError) else "Ads API request failed."})
