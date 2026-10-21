"""MomoBot About copy, Agents lineup and their assets, read from ``momobot_brand.content_dir``.

404 everywhere when the folder is not configured, so a public build shows nothing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app import momobot_brand as brand

router = APIRouter(prefix="/api/momobot-brand", tags=["momobot-brand"])


def _dir() -> Path:
    d = brand.configured_content_dir()
    if d is None or not d.is_dir():
        raise HTTPException(status_code=404, detail="Not available")
    return d


@router.get("/kit")
def get_kit() -> dict[str, Any]:
    try:
        return brand.load_kit(_dir())
    except (OSError, ValueError):
        raise HTTPException(status_code=404, detail="Not available") from None


@router.get("/about")
def get_about() -> dict[str, Any]:
    d = _dir()
    try:
        return {"markdown": brand.load_about(d), "show_pricing": brand.load_kit(d)["show_pricing"]}
    except (OSError, ValueError):
        raise HTTPException(status_code=404, detail="Not available") from None


@router.get("/assets/{path:path}")
def get_asset(path: str) -> FileResponse:
    target = brand.resolve_asset(_dir(), path)
    if target is None:
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(target, headers={"Cache-Control": "private, max-age=3600"})
