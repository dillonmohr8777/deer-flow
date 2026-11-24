"""Host-owned public route for weekly Monday zero-typing facility vacancy pulse forms.

Fail-closed by default: mounted ONLY when ``VHIN_PULSE_SECRET`` is configured.
Authenticates exclusively via HMAC-SHA256 signed 7-day tokens scoped to a single
contracted facility (zero MomoBot login required, zero PHI exposed).
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

router = APIRouter(prefix="/api/public/vhin-pulse", tags=["vhin-pulse"])


def is_route_enabled() -> bool:
    return bool(os.environ.get("VHIN_PULSE_SECRET", "").strip())


def _find_vhin_service(request: Request) -> Any:
    extensions = getattr(request.app.state, "extensions", None)
    services = getattr(extensions, "services", ()) if extensions is not None else ()
    for service in services:
        if hasattr(service, "inspect_public_pulse") and hasattr(service, "record_public_pulse"):
            return service
    raise HTTPException(404, "Facility pulse service is not active")


@router.get("/{token}", response_class=HTMLResponse)
async def get_pulse_form(token: str, request: Request) -> HTMLResponse:
    service = _find_vhin_service(request)
    info = service.inspect_public_pulse(token)
    from vhin_placement.pulse import render_pulse_form_html

    html_body = render_pulse_form_html(
        info["community_name"],
        info["week_iso"],
        action_url=f"/api/public/vhin-pulse/{token}",
        current=info.get("current_pulse"),
    )
    return HTMLResponse(html_body, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@router.post("/{token}", response_class=HTMLResponse)
async def submit_pulse_form(token: str, request: Request) -> HTMLResponse:
    service = _find_vhin_service(request)
    content_type = (request.headers.get("content-type") or "").lower()
    if "application/json" in content_type:
        raw = await request.json()
    else:
        form = await request.form()
        raw = {
            "private_rooms": str(form.get("private_rooms") or ""),
            "semi_private_male_rooms": str(form.get("semi_private_male_rooms") or ""),
            "semi_private_female_rooms": str(form.get("semi_private_female_rooms") or ""),
            "rate_changed": str(form.get("rate_changed") or "no").lower() in ("yes", "true", "1", "on"),
            "rate_change_note": str(form.get("rate_change_note") or ""),
        }
    from pydantic import ValidationError
    from vhin_placement.models import PulseSubmission
    from vhin_placement.pulse import render_pulse_result_html

    try:
        submission = PulseSubmission.model_validate(raw)
    except ValidationError as exc:
        raise HTTPException(422, exc.errors()) from None
    saved = service.record_public_pulse(token, submission)
    html_body = render_pulse_result_html(saved["community_name"], saved["week_iso"], saved["pulse"])
    return HTMLResponse(html_body, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
