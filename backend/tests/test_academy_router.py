"""AI Academy: staff-only curriculum and each person's own progress."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from org_isolation_fixtures import ORG_S, USER_A, USER_C, auth_headers, org_world  # noqa: F401

from app.gateway.academy_content import TRACKS, lesson_ids
from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.deps import get_config
from app.gateway.routers import academy
from deerflow.persistence.academy import AcademyProgressRepository
from deerflow.persistence.organizations.model import OrganizationMemberRow
from deerflow.persistence.user.model import UserRow

USER_CLIENT = "user-client"


def _build_app(session_factory, *, private_workspace: bool = True) -> FastAPI:
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.state.academy_progress_repo = AcademyProgressRepository(session_factory)
    app.include_router(academy.router)
    app.dependency_overrides[get_config] = lambda: SimpleNamespace(private_workspace=SimpleNamespace(enabled=private_workspace))
    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _lesson_flags(payload: dict) -> dict[str, bool]:
    return {lesson["id"]: lesson["completed"] for track in payload["tracks"] for lesson in track["lessons"]}


@pytest.mark.asyncio
async def test_staff_read_curriculum_and_track_their_own_progress(org_world):  # noqa: F811
    app = _build_app(org_world)
    owner, admin = auth_headers(USER_A, ORG_S), auth_headers(USER_C, ORG_S)
    first = TRACKS[0]["lessons"][0]["id"]

    async with _client(app) as client:
        fresh = await client.get("/api/academy", headers=owner)
        assert fresh.status_code == 200, fresh.text
        body = fresh.json()
        assert body["lesson_count"] == len(lesson_ids())
        assert body["completed_count"] == 0
        assert not any(_lesson_flags(body).values())

        assert (await client.put(f"/api/academy/lessons/{first}/progress", json={"completed": True}, headers=owner)).status_code == 204
        # Marking twice is harmless.
        assert (await client.put(f"/api/academy/lessons/{first}/progress", json={"completed": True}, headers=owner)).status_code == 204
        mine = (await client.get("/api/academy", headers=owner)).json()
        assert mine["completed_count"] == 1
        assert _lesson_flags(mine)[first] is True

        # Progress is per person: the admin in the same workspace starts clean.
        theirs = (await client.get("/api/academy", headers=admin)).json()
        assert theirs["completed_count"] == 0

        assert (await client.put(f"/api/academy/lessons/{first}/progress", json={"completed": False}, headers=owner)).status_code == 204
        assert (await client.get("/api/academy", headers=owner)).json()["completed_count"] == 0

        assert (await client.put("/api/academy/lessons/not-a-lesson/progress", json={"completed": True}, headers=owner)).status_code == 404


@pytest.mark.asyncio
async def test_clients_and_client_facing_instances_get_404(org_world):  # noqa: F811
    now = datetime.now(UTC)
    async with org_world() as session, session.begin():
        session.add(UserRow(id=USER_CLIENT, email="client@example.com", password_hash=None, system_role="user", needs_setup=False, token_version=0, created_at=now))
        session.add(OrganizationMemberRow(organization_id=ORG_S, user_id=USER_CLIENT, role="client", status="active", created_at=now, updated_at=now))
    first = TRACKS[0]["lessons"][0]["id"]

    async with _client(_build_app(org_world)) as client:
        headers = auth_headers(USER_CLIENT, ORG_S)
        assert (await client.get("/api/academy", headers=headers)).status_code == 404
        assert (await client.put(f"/api/academy/lessons/{first}/progress", json={"completed": True}, headers=headers)).status_code == 404

    async with _client(_build_app(org_world, private_workspace=False)) as client:
        headers = auth_headers(USER_A, ORG_S)
        assert (await client.get("/api/academy", headers=headers)).status_code == 404
        assert (await client.put(f"/api/academy/lessons/{first}/progress", json={"completed": True}, headers=headers)).status_code == 404


def test_curriculum_is_well_formed():
    ids = [lesson["id"] for track in TRACKS for lesson in track["lessons"]]
    assert len(ids) == len(set(ids)), "lesson ids must be unique; progress rows key on them"
    assert all(len(lesson_id) <= 64 for lesson_id in ids), "academy_progress.lesson_id is String(64)"

    # The MomoBot track pairs one lesson with each of the six explainer videos.
    momobot = next(track for track in TRACKS if track["id"] == "momobot")
    assert [lesson["video_slot"] for lesson in momobot["lessons"]] == [f"momo-0{n}" for n in range(1, 7)]

    for track in TRACKS:
        for lesson in track["lessons"]:
            assert lesson["steps"], lesson["id"]
            assert lesson["try_it"], lesson["id"]
            text = " ".join([lesson["title"], lesson["summary"], lesson["try_it"], *lesson["steps"]])
            # House style: no em dashes in product copy.
            assert "—" not in text, lesson["id"]
