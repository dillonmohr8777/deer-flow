"""POST /api/clients/import (Momentum Phase 2 item 3): admin-only, upserts by
``registry_id``, never deletes. The fixture below is synthetic -- shaped like
``client-operations/registry/clients.json`` (schemaVersion/generatedAt/
communicationScan envelope + a ``clients`` roster) but with invented names,
never real client data.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from org_isolation_fixtures import USER_A, auth_headers, org_world  # noqa: F401

from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.routers import clients
from deerflow.persistence.clients import ClientRepository

pytestmark = pytest.mark.asyncio

# Synthetic, registry-shaped fixture -- no real client data.
_SYNTHETIC_REGISTRY = {
    "schemaVersion": 1,
    "generatedAt": "2026-01-01T00:00:00.000Z",
    "communicationScan": {"status": "complete-live"},
    "clients": [
        {
            "id": "fixture-co",
            "displayName": "Fixture Co",
            "aliases": ["FixtureCo"],
            "status": "active",
            "folder": "clients/fixture-co",
            "emailDomains": ["fixtureco.example"],
            "contacts": [{"email": "owner@fixtureco.example", "role": "authorized operator"}],
            "slackChannels": ["C0FIXTURE"],
            "accessRefs": ["fixture-access-ref"],
            "lastEvidenceAt": "2026-01-01",
            "evidence": ["synthetic fixture"],
        },
        {
            "id": "sample-studio",
            "displayName": "Sample Studio",
            "aliases": [],
            "status": "prospect",
            "folder": "clients/sample-studio",
            "emailDomains": ["samplestudio.example"],
            "contacts": [],
            "slackChannels": [],
            "accessRefs": [],
            "lastEvidenceAt": "2026-01-01",
            "evidence": [],
        },
        # No `id` -- must be skipped, not crash the batch.
        {"displayName": "No Registry Id", "status": "active"},
    ],
}


async def _admin_user_from_access_token(request):
    return SimpleNamespace(id=request.cookies["access_token"], system_role="admin", email="registry-import@example.com")


@pytest.fixture()
def admin_org_world(org_world, monkeypatch):  # noqa: F811
    """The shared org world, but every actor resolves as an admin."""
    monkeypatch.setattr("app.gateway.deps.get_current_user_from_request", _admin_user_from_access_token)
    return org_world


def _build_app(session_factory):
    from fastapi import FastAPI

    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.state.client_repo = ClientRepository(session_factory)
    app.include_router(clients.router)
    return app


def _client(app):
    import httpx

    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_import_requires_admin():
    """Non-admin callers 403 before the repository is ever touched."""
    from unittest.mock import MagicMock

    from _router_auth_helpers import make_authed_test_app

    app = make_authed_test_app()  # default stub user has system_role="user"
    app.state.client_repo = MagicMock()
    app.include_router(clients.router)

    async with _client(app) as client:
        response = await client.post("/api/clients/import", json={"clients": []})

    assert response.status_code == 403
    app.state.client_repo.upsert_by_registry_id.assert_not_called()


async def test_import_creates_updates_skips_and_never_deletes(admin_org_world):
    session_factory = admin_org_world
    app = _build_app(session_factory)
    headers = auth_headers(USER_A)

    async with _client(app) as client:
        first = await client.post("/api/clients/import", json=_SYNTHETIC_REGISTRY, headers=headers)
        assert first.status_code == 200, first.text
        body = first.json()
        assert body["created"] == 2
        assert body["updated"] == 0
        assert body["skipped"] == 1
        assert "<missing id>" in body["skipped_ids"]

        listing = await client.get("/api/clients", headers=headers)
        names = {c["display_name"] for c in listing.json()["clients"]}
        assert names == {"Fixture Co", "Sample Studio"}

        # Re-importing the same roster (one entry renamed) upserts by
        # registry_id -- update, never a duplicate, and nothing is removed
        # even though this second payload omits "sample-studio" entirely.
        renamed = {**_SYNTHETIC_REGISTRY, "clients": [{**_SYNTHETIC_REGISTRY["clients"][0], "displayName": "Fixture Co Renamed"}]}
        second = await client.post("/api/clients/import", json=renamed, headers=headers)
        assert second.status_code == 200, second.text
        body2 = second.json()
        assert body2["created"] == 0
        assert body2["updated"] == 1
        assert body2["skipped"] == 0

        listing2 = await client.get("/api/clients", headers=headers)
        names2 = {c["display_name"] for c in listing2.json()["clients"]}
        assert names2 == {"Fixture Co Renamed", "Sample Studio"}, "import must never delete an existing client"
