"""Read-only spend per cost-router route, for today and this month (admin only)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.gateway.deps import require_admin_user
from deerflow.config.app_config import get_app_config
from deerflow.runtime.cost_router import spend_report

router = APIRouter(prefix="/api/cost-router", tags=["cost-router"])


@router.get("/spend")
async def get_spend(request: Request) -> dict:
    """USD spent per route today and this month (UTC), with caps and unpriced flags."""
    await require_admin_user(request, detail="System administrator privileges are required.")
    return await spend_report(get_app_config(), request.app.state.run_store)
