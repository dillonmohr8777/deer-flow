"""Signed zero-typing weekly Monday vacancy pulse tokens and HTML rendering.

Zero PHI: tokens carry only ``community_id``, ``week_iso``, and expiry timestamp,
signed with HMAC-SHA256 using an operator-provided secret. Contracted ALFs,
Adult Family Care Homes, and Memory Care homes click one link and tap 4 fields:
1. Available Private Rooms (0, 1, 2, 3, 4, 5+)
2. Available Semi-Private Rooms - Male (0, 1, 2, 3, 4, 5+)
3. Available Semi-Private Rooms - Female (0, 1, 2, 3, 4, 5+)
4. Monthly rate change since tour/last check? No (status quo) vs Yes (+ 1-line note)
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

BUCKETS = ("0", "1", "2", "3", "4", "5+")
ET = ZoneInfo("America/New_York")


def current_week_iso(stamp: datetime) -> str:
    local = stamp.astimezone(ET)
    iso = local.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def bucket_min_count(bucket: str) -> int:
    return 5 if bucket == "5+" else int(bucket)


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def create_pulse_token(community_id: str, secret: str, stamp: datetime, *, ttl_days: int = 7) -> tuple[str, str, str]:
    """Return ``(token, week_iso, expires_at_iso)`` for one contracted facility."""
    if not secret or not secret.strip():
        raise ValueError("Pulse signing secret is required")
    week_iso = current_week_iso(stamp)
    expires_at = stamp + timedelta(days=ttl_days)
    payload = {"cid": community_id, "week": week_iso, "exp": int(expires_at.timestamp())}
    body = _b64encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    sig = _b64encode(hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{sig}", week_iso, expires_at.isoformat()


def verify_pulse_token(token: str, secret: str, stamp: datetime) -> dict:
    """Validate signature and expiry; raise ValueError if forged, malformed, or expired."""
    if not secret or not secret.strip():
        raise ValueError("Pulse signing secret is not configured")
    parts = token.split(".")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError("Malformed pulse token")
    body, provided_sig = parts
    expected_sig = _b64encode(hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest())
    if not hmac.compare_digest(provided_sig, expected_sig):
        raise ValueError("Invalid pulse signature")
    try:
        payload = json.loads(_b64decode(body).decode("utf-8"))
    except Exception as exc:
        raise ValueError("Malformed pulse payload") from exc
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("cid"), str)
        or not isinstance(payload.get("week"), str)
        or not isinstance(payload.get("exp"), int)
    ):
        raise ValueError("Incomplete pulse payload")
    if int(stamp.timestamp()) > payload["exp"]:
        raise ValueError("Pulse link has expired")
    return payload


def _options(selected: str = "0") -> str:
    return "".join(f'<option value="{b}"{" selected" if b == selected else ""}>{b}</option>' for b in BUCKETS)


def render_pulse_form_html(community_name: str, week_iso: str, action_url: str, current: dict | None = None) -> str:
    """Render a zero-typing mobile-friendly HTML form (10 seconds to submit, zero PHI)."""
    cur = current or {}
    priv = cur.get("private_rooms") or "0"
    sm = cur.get("semi_private_male_rooms") or "0"
    sf = cur.get("semi_private_female_rooms") or "0"
    changed = bool(cur.get("rate_changed", False))
    note = html.escape(cur.get("rate_change_note") or "")
    safe_name = html.escape(community_name)
    safe_week = html.escape(week_iso)
    safe_action = html.escape(action_url)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>Weekly Vacancy Check-In | {safe_name}</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#f6f7f9;color:#111827;margin:0;padding:16px}}
main{{max-width:480px;margin:12px auto;background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:20px}}
h1{{font-size:20px;margin:0 0 4px}}
p.sub{{color:#4b5563;font-size:14px;margin:0 0 18px}}
label{{display:block;font-weight:600;font-size:14px;margin:14px 0 6px}}
select,input[type=text]{{width:100%;box-sizing:border-box;font-size:16px;padding:10px 12px;border:1px solid #d1d5db;border-radius:8px;background:#fff}}
.radio-row{{display:flex;gap:12px;margin-top:6px}}
.radio-row label{{display:flex;align-items:center;gap:6px;font-weight:500;
margin:0;padding:10px 14px;border:1px solid #d1d5db;border-radius:8px;cursor:pointer;flex:1}}
#rate-note-wrap{{margin-top:10px}}
button{{margin-top:20px;width:100%;padding:12px;font-size:16px;font-weight:600;background:#111827;color:#fff;border:0;border-radius:8px;cursor:pointer}}
</style>
</head>
<body>
<main>
<h1>{safe_name}</h1>
<p class="sub">Weekly Monday Vacancy Check-In ({safe_week}) — takes 10 seconds.</p>
<form method="post" action="{safe_action}">
<label for="private_rooms">1. Available Private Rooms</label>
<select id="private_rooms" name="private_rooms" required>{_options(priv)}</select>

<label for="semi_private_male_rooms">2. Available Semi-Private Rooms (Male)</label>
<select id="semi_private_male_rooms" name="semi_private_male_rooms" required>{_options(sm)}</select>

<label for="semi_private_female_rooms">3. Available Semi-Private Rooms (Female)</label>
<select id="semi_private_female_rooms" name="semi_private_female_rooms" required>{_options(sf)}</select>

<label>4. Any changes in monthly rates since our tour or last check?</label>
<div class="radio-row">
  <label><input type="radio" name="rate_changed" value="no" {"" if changed else "checked"}
    onclick="document.getElementById('rate-note-wrap').hidden=true"> No (status quo)</label>
  <label><input type="radio" name="rate_changed" value="yes" {"checked" if changed else ""}
    onclick="document.getElementById('rate-note-wrap').hidden=false"> Yes</label>
</div>
<div id="rate-note-wrap" {"" if changed else "hidden"}>
  <label for="rate_change_note">Brief rate update (1 line)</label>
  <input id="rate_change_note" name="rate_change_note" type="text" maxlength="500" placeholder="e.g., Private suites now start at $5,800/mo" value="{note}">
</div>
<button type="submit">Submit weekly update</button>
</form>
</main>
</body>
</html>"""


def render_pulse_result_html(community_name: str, week_iso: str, pulse: dict) -> str:
    safe_name = html.escape(community_name)
    safe_week = html.escape(week_iso)
    rate_note = html.escape(pulse.get("rate_change_note") or "Changed")
    rate_line = f"Rate update noted: {rate_note}" if pulse.get("rate_changed") else "Monthly rates: No change (status quo)"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>Update Received | {safe_name}</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#f6f7f9;color:#111827;margin:0;padding:16px}}
main{{max-width:480px;margin:24px auto;background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:24px}}
h1{{font-size:20px;margin:0 0 8px}}
p{{color:#374151;line-height:1.5}}
ul{{padding-left:18px;color:#111827}}
</style>
</head>
<body>
<main>
<h1>Thank you, {safe_name} is updated</h1>
<p>Recorded for week {safe_week}:</p>
<ul>
<li>Private rooms open: <strong>{html.escape(str(pulse["private_rooms"]))}</strong></li>
<li>Semi-private male open: <strong>{html.escape(str(pulse["semi_private_male_rooms"]))}</strong></li>
<li>Semi-private female open: <strong>{html.escape(str(pulse["semi_private_female_rooms"]))}</strong></li>
<li>{rate_line}</li>
</ul>
<p>You can close this page. If anything changes this week, submit the same link again to update.</p>
</main>
</body>
</html>"""
