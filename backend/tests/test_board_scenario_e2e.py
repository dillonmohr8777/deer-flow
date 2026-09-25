"""Momo Board scenario end-to-end run (Workspace Phase 4 item b7).

Drives every thread in b6's ``board_scenarios.yaml`` through the real
pipeline pieces already built: the ``/api/board`` router (b2) for posting
and messages, ``triage_board_thread`` (b3) -- with its model stubbed to
answer from the fixture's own ``expected`` block, mirroring
``test_board_triage.py``'s fake-model pattern -- to decide ``draft`` vs
``escalate``, and the draft/approve/reply workflow (b4), also through the
router. Each scenario's actual outcome is checked against its catalog
``expected`` block and a summary table is printed. Isolation is checked at
catalog scale: with one staff member assigned to each of the 8 clients (the
same ``client_assignments`` shape ``test_board_router.py`` exercises
narrowly), no client's staff can see another client's threads, messages, or
name.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from fixtures.seed_board_scenarios import load_catalog, validate_catalog
from org_isolation_fixtures import ORG_S, USER_A, auth_headers, org_world  # noqa: F401

from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.routers import board, clients
from deerflow.board.triage import triage_board_thread
from deerflow.persistence.audit_events import AuditEventRepository
from deerflow.persistence.board import BoardRepository
from deerflow.persistence.clients import ClientRepository
from deerflow.persistence.fleet import FleetBindingRepository
from deerflow.persistence.organizations.model import OrganizationMemberRow
from deerflow.persistence.user.model import UserRow

pytestmark = pytest.mark.asyncio


def _build_app(session_factory) -> FastAPI:
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.state.client_repo = ClientRepository(session_factory)
    app.state.board_repo = BoardRepository(session_factory)
    app.state.fleet_binding_repo = FleetBindingRepository(session_factory)
    app.state.audit_repo = AuditEventRepository(session_factory)
    app.include_router(clients.router)
    app.include_router(board.router)
    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _add_plain_member(session_factory, user_id: str, organization_id: str) -> None:
    """Seed a member (neither owner nor admin) of *organization_id*, one per catalog client.

    Copies ``test_board_router.py``'s helper of the same name so this file
    doesn't add a shared dependency for a single small fixture.
    """
    now = datetime.now(UTC)
    async with session_factory() as session, session.begin():
        session.add(UserRow(id=user_id, email=f"{user_id}@example.com", password_hash=None, system_role="user", needs_setup=False, token_version=0, created_at=now))
        session.add(OrganizationMemberRow(organization_id=organization_id, user_id=user_id, role="member", status="active", created_at=now, updated_at=now))


class _FixtureTriageModel:
    """Stands in for the real chat model in ``triage_board_thread``: answers
    every classification from the catalog's own ``expected`` block, keyed by
    the message body it's asked to classify (bodies are unique across the
    catalog -- see ``test_thread_ids_are_globally_unique``'s sibling check in
    ``test_board_scenarios_catalog.py``)."""

    def __init__(self, threads_by_body: dict[str, dict[str, Any]]) -> None:
        self._threads_by_body = threads_by_body

    async def ainvoke(self, messages, config=None):  # noqa: ARG002 -- mirrors the real model's signature
        prompt = messages[-1]["content"]
        for body, thread in self._threads_by_body.items():
            if body in prompt:
                payload = {
                    "kind": thread["kind"],
                    "urgency": thread["expected"]["urgency"],
                    "action": thread["expected"]["action"],
                    "summary": f"{thread['situation'].replace('-', ' ')}: {thread['subject']}"[:139],
                }
                return SimpleNamespace(content=json.dumps(payload))
        raise AssertionError(f"fixture triage model got a prompt with no matching catalog thread: {prompt[:200]!r}")


def _safe_draft_body(client_name: str, subject: str) -> str:
    """A single generic, non-committal canned reply -- never derived from
    another client's data, never confirms an action was taken."""
    return f'Hi {client_name} team, thanks for the note about "{subject}". Momo has flagged this for the account team to follow up on shortly.'


@pytest_asyncio.fixture()
async def board_world(org_world, monkeypatch):  # noqa: F811
    session_factory = org_world
    catalog = load_catalog()
    validate_catalog(catalog)

    threads_by_body = {t["body"]: t for c in catalog["clients"] for t in c["threads"]}
    monkeypatch.setattr("deerflow.board.triage.get_app_config", lambda: SimpleNamespace())
    monkeypatch.setattr("deerflow.board.triage.create_chat_model", lambda **_kwargs: _FixtureTriageModel(threads_by_body))

    app = _build_app(session_factory)
    owner_headers = auth_headers(USER_A, ORG_S)

    async with _client(app) as client:
        clients_by_slug: dict[str, dict[str, Any]] = {}
        threads_by_slug: dict[str, dict[str, Any]] = {}

        for c in catalog["clients"]:
            created_client = await client.post("/api/clients", json={"display_name": c["name"]}, headers=owner_headers)
            assert created_client.status_code == 201, created_client.text
            client_id = created_client.json()["id"]

            staff_user_id = f"staff-{c['id']}"
            await _add_plain_member(session_factory, staff_user_id, ORG_S)
            assigned = await client.post(f"/api/clients/{client_id}/assignments", json={"user_id": staff_user_id, "role": "account_manager"}, headers=owner_headers)
            assert assigned.status_code == 201, assigned.text
            staff_headers = auth_headers(staff_user_id, ORG_S)

            clients_by_slug[c["id"]] = {"id": client_id, "name": c["name"], "staff_headers": staff_headers}

            for t in c["threads"]:
                created_thread = await client.post("/api/board/threads", json={"client_id": client_id, "kind": t["kind"], "subject": t["subject"]}, headers=staff_headers)
                assert created_thread.status_code == 201, created_thread.text
                thread_id = created_thread.json()["id"]

                posted = await client.post(f"/api/board/threads/{thread_id}/messages", json={"author_kind": "client", "body": t["body"]}, headers=staff_headers)
                assert posted.status_code == 201, posted.text

                threads_by_slug[t["id"]] = {**t, "thread_id": thread_id, "client_slug": c["id"]}

        yield SimpleNamespace(
            client=client,
            catalog=catalog,
            owner_headers=owner_headers,
            clients_by_slug=clients_by_slug,
            threads_by_slug=threads_by_slug,
            session_factory=session_factory,
        )


def _print_summary_table(rows: list[tuple[str, str, str, str, str, bool]]) -> None:
    header = f"{'scenario':<28} {'exp action':<11} {'got action':<11} {'exp urgency':<12} {'got urgency':<12} {'ok':<3}"
    print("\n" + header)
    print("-" * len(header))
    for slug, exp_action, got_action, exp_urgency, got_urgency, ok in rows:
        print(f"{slug:<28} {exp_action:<11} {got_action:<11} {exp_urgency:<12} {got_urgency:<12} {'yes' if ok else 'NO':<3}")


async def test_every_catalog_scenario_reaches_its_expected_outcome(board_world):  # noqa: F811
    client = board_world.client
    owner_headers = board_world.owner_headers
    audit_repo = AuditEventRepository(board_world.session_factory)

    rows: list[tuple[str, str, str, str, str, bool]] = []
    failures: list[str] = []

    for slug, thread in board_world.threads_by_slug.items():
        client_info = board_world.clients_by_slug[thread["client_slug"]]
        thread_id = thread["thread_id"]
        staff_headers = client_info["staff_headers"]
        expected = thread["expected"]

        triage = await triage_board_thread(thread["body"], subject=thread["subject"])

        # Triage always classifies before anything else happens to the thread.
        triaged = await client.patch(f"/api/board/threads/{thread_id}", json={"status": "triaged"}, headers=staff_headers)
        assert triaged.status_code == 200, triaged.text

        expected_final_status = "triaged"
        if triage.action == "draft":
            draft_body = _safe_draft_body(client_info["name"], thread["subject"])
            for phrase in expected["forbidden_phrases"]:
                assert phrase.lower() not in draft_body.lower(), f"{slug}: canned draft body must not contain forbidden phrase {phrase!r}"

            drafted = await client.post(f"/api/board/threads/{thread_id}/draft", json={"body": draft_body}, headers=owner_headers)
            assert drafted.status_code == 200, drafted.text
            approved = await client.post(f"/api/board/threads/{thread_id}/approve", headers=owner_headers)
            assert approved.status_code == 200, approved.text
            replied = await client.post(f"/api/board/threads/{thread_id}/reply", json={"body": draft_body}, headers=owner_headers)
            assert replied.status_code == 200, replied.text
            expected_final_status = "replied"

        thread_after = await client.get(f"/api/board/threads/{thread_id}", headers=staff_headers)
        assert thread_after.status_code == 200, thread_after.text
        actual_status = thread_after.json()["status"]

        messages = (await client.get(f"/api/board/threads/{thread_id}/messages", headers=staff_headers)).json()["messages"]
        drafted_or_sent_text = " ".join(m["body"] for m in messages if m["author_kind"] in ("momo", "owner")).lower()
        for phrase in expected["forbidden_phrases"]:
            assert phrase.lower() not in drafted_or_sent_text, f"{slug}: a drafted/sent reply must never contain forbidden phrase {phrase!r}"

        if expected["action"] == "escalate":
            assert not any(m["author_kind"] == "momo" for m in messages), f"{slug}: an escalate scenario must never get a Momo-authored draft"
            assert actual_status != "approved" and actual_status != "replied", f"{slug}: a must-refuse/escalate scenario must never reach {actual_status!r} without an owner edit"

        ok = actual_status == expected_final_status and triage.action == expected["action"] and triage.urgency == expected["urgency"]
        rows.append((slug, expected["action"], triage.action, expected["urgency"], triage.urgency, ok))
        if not ok:
            failures.append(slug)

    _print_summary_table(rows)
    assert not failures, f"scenarios with an unexpected outcome: {failures}"

    # Every drafted scenario carries a complete draft -> approve -> reply audit trail.
    audit_rows, _ = await audit_repo.list(organization_id=ORG_S, action_prefix="board.thread.", limit=500)
    audit_actions_by_thread: dict[str, set[str]] = {}
    for row in audit_rows:
        audit_actions_by_thread.setdefault(row["target_id"], set()).add(row["action"])
    for thread in board_world.threads_by_slug.values():
        if thread["expected"]["action"] == "draft":
            actions = audit_actions_by_thread.get(thread["thread_id"], set())
            assert {"board.thread.drafted", "board.thread.approved", "board.thread.replied"} <= actions, f"{thread['id']}: incomplete audit trail: {actions}"


async def test_no_client_can_see_another_clients_threads_messages_or_name(board_world):  # noqa: F811
    client = board_world.client

    for slug, info in board_world.clients_by_slug.items():
        listing = await client.get("/api/board/threads", headers=info["staff_headers"])
        assert listing.status_code == 200, listing.text
        payload = listing.json()
        listed_client_ids = {t["client_id"] for t in payload["threads"]}
        assert listed_client_ids == {info["id"]}, f"{slug}: staff assigned to one client saw threads for {listed_client_ids}"

        raw_text = listing.text
        for other_slug, other_info in board_world.clients_by_slug.items():
            if other_slug == slug:
                continue
            assert other_info["name"] not in raw_text, f"{slug}'s own thread listing leaked another client's name {other_info['name']!r}"

        other_slug = next(s for s in board_world.clients_by_slug if s != slug)
        other_thread = next(t for t in board_world.threads_by_slug.values() if t["client_slug"] == other_slug)

        cross_thread = await client.get(f"/api/board/threads/{other_thread['thread_id']}", headers=info["staff_headers"])
        assert cross_thread.status_code == 404

        cross_messages = await client.get(f"/api/board/threads/{other_thread['thread_id']}/messages", headers=info["staff_headers"])
        assert cross_messages.status_code == 404
