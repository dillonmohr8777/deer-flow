"""Tests for GET /api/fleet/templates."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import yaml
from fastapi import FastAPI
from org_isolation_fixtures import USER_A, auth_headers, org_world  # noqa: F401

from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.routers import fleet

pytestmark = pytest.mark.asyncio


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.include_router(fleet.router)
    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_list_fleet_templates_requires_auth(org_world):  # noqa: F811
    app = _build_app()
    async with _client(app) as client:
        response = await client.get("/api/fleet/templates")
    assert response.status_code == 401


async def test_list_fleet_templates_returns_the_real_catalog(org_world, monkeypatch):  # noqa: F811
    monkeypatch.setenv("DEER_FLOW_PROJECT_ROOT", str(Path(__file__).resolve().parents[2]))
    app = _build_app()
    async with _client(app) as client:
        response = await client.get("/api/fleet/templates", headers=auth_headers(USER_A))

    assert response.status_code == 200
    body = response.json()
    ids = {t["id"] for t in body["templates"]}
    assert ids == {"weekly-client-report", "ai-search-visibility", "content-drafts", "review-replies"}
    report = next(t for t in body["templates"] if t["id"] == "weekly-client-report")
    assert report["schedule"] == {"cron": "0 8 * * 1", "timezone": "America/New_York"}
    assert report["acceptance_criteria"]
    assert report["model"] == "openrouter-sonnet-5"
    assert "soul" not in report


async def test_list_fleet_templates_empty_catalog(org_world, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setenv("DEER_FLOW_PROJECT_ROOT", str(tmp_path))
    app = _build_app()
    async with _client(app) as client:
        response = await client.get("/api/fleet/templates", headers=auth_headers(USER_A))
    assert response.status_code == 200
    assert response.json() == {"templates": []}


async def test_list_fleet_templates_malformed_template_is_a_clear_500(org_world, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setenv("DEER_FLOW_PROJECT_ROOT", str(tmp_path))
    template_dir = tmp_path / "fleet" / "templates" / "broken"
    template_dir.mkdir(parents=True)
    (template_dir / "template.yaml").write_text(yaml.safe_dump({"id": "broken", "unexpected": "field"}), encoding="utf-8")

    app = _build_app()
    async with _client(app) as client:
        response = await client.get("/api/fleet/templates", headers=auth_headers(USER_A))

    assert response.status_code == 500
    assert "broken" in response.json()["detail"]
