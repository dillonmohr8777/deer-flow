"""Momo Board item e2: run b3's triage when a thread is created and persist
its ``urgency``/``summary`` onto the thread.

Mirrors ``test_board_triage.py``'s fake-model monkeypatch pattern (mocks
``deerflow.board.triage.create_chat_model``, no real API calls) and
``test_board_router.py``'s app-building helpers.
"""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from org_isolation_fixtures import ORG_S, USER_A, auth_headers, org_world  # noqa: F401

from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.routers import board, clients
from deerflow.persistence.board import BoardRepository
from deerflow.persistence.clients import ClientRepository
from deerflow.persistence.fleet import FleetBindingRepository

pytestmark = pytest.mark.asyncio


def _build_app(session_factory) -> FastAPI:
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.state.client_repo = ClientRepository(session_factory)
    app.state.board_repo = BoardRepository(session_factory)
    app.state.fleet_binding_repo = FleetBindingRepository(session_factory)
    app.include_router(clients.router)
    app.include_router(board.router)
    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _mock_model(monkeypatch, response_content):
    """Mirrors ``test_board_triage.py``'s ``_make_env``."""
    config = SimpleNamespace()
    fake_response = SimpleNamespace(content=response_content)

    class FakeModel:
        async def ainvoke(self, *args, **kwargs):
            return fake_response

    monkeypatch.setattr("deerflow.board.triage.get_app_config", lambda: config)
    monkeypatch.setattr("deerflow.board.triage.create_chat_model", lambda **kwargs: FakeModel())


async def test_thread_creation_persists_triage_classification(org_world, monkeypatch):  # noqa: F811
    _mock_model(monkeypatch, '{"kind":"concern","urgency":"urgent","summary":"Site is down for everyone."}')
    app = _build_app(org_world)
    headers_a = auth_headers(USER_A, ORG_S)

    async with _client(app) as client:
        client_row = (await client.post("/api/clients", json={"display_name": "Acme"}, headers=headers_a)).json()
        created = await client.post(
            "/api/board/threads",
            json={"client_id": client_row["id"], "kind": "ticket", "subject": "Site down"},
            headers=headers_a,
        )
        assert created.status_code == 201, created.text
        thread = created.json()

        # Classification is persisted, but the client-supplied ``kind`` at
        # creation time is left alone -- e2 only wires urgency/summary.
        assert thread["status"] == "triaged"
        assert thread["urgency"] == "urgent"
        assert thread["summary"] == "Site is down for everyone."
        assert thread["kind"] == "ticket"

        # Fetching the thread again returns the same persisted values.
        fetched = (await client.get(f"/api/board/threads/{thread['id']}", headers=headers_a)).json()
        assert fetched["status"] == "triaged"
        assert fetched["urgency"] == "urgent"
        assert fetched["summary"] == "Site is down for everyone."


async def test_thread_creation_falls_back_when_model_call_fails(org_world, monkeypatch):  # noqa: F811
    """A model failure never blocks creation -- the thread still lands with
    ``triage_board_thread``'s own safe-default classification."""

    config = SimpleNamespace()

    class ExplodingModel:
        async def ainvoke(self, *args, **kwargs):
            raise RuntimeError("model provider unreachable")

    monkeypatch.setattr("deerflow.board.triage.get_app_config", lambda: config)
    monkeypatch.setattr("deerflow.board.triage.create_chat_model", lambda **kwargs: ExplodingModel())

    app = _build_app(org_world)
    headers_a = auth_headers(USER_A, ORG_S)

    async with _client(app) as client:
        client_row = (await client.post("/api/clients", json={"display_name": "Acme"}, headers=headers_a)).json()
        created = await client.post(
            "/api/board/threads",
            json={"client_id": client_row["id"], "kind": "ticket", "subject": "Broken widget"},
            headers=headers_a,
        )
        assert created.status_code == 201, created.text
        thread = created.json()

        assert thread["status"] == "triaged"
        assert thread["urgency"] == "normal"
        assert thread["summary"] == "Broken widget"


async def test_thread_creation_survives_triage_itself_raising(org_world, monkeypatch):  # noqa: F811
    """Even if something above ``triage_board_thread``'s own safety net breaks
    (e.g. the DB patch call), thread creation still returns 201 with the
    thread left in its pre-triage state rather than a 500."""

    async def _boom(*args, **kwargs):
        raise RuntimeError("unexpected triage failure")

    monkeypatch.setattr("app.gateway.routers.board.triage_board_thread", _boom)

    app = _build_app(org_world)
    headers_a = auth_headers(USER_A, ORG_S)

    async with _client(app) as client:
        client_row = (await client.post("/api/clients", json={"display_name": "Acme"}, headers=headers_a)).json()
        created = await client.post(
            "/api/board/threads",
            json={"client_id": client_row["id"], "kind": "ticket", "subject": "Broken widget"},
            headers=headers_a,
        )
        assert created.status_code == 201, created.text
        thread = created.json()

        assert thread["status"] == "new"
        assert thread["urgency"] is None
        assert thread["summary"] is None
