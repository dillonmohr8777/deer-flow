"""Approvals inbox: tenancy, state machine, and 'nothing executes before approval'.

Drives the real router behind the real AuthMiddleware and the shared
``org_isolation_fixtures`` world, plus repository- and tool-level checks.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
from alembic import command
from alembic.script import ScriptDirectory
from fastapi import FastAPI
from org_isolation_fixtures import ORG_S, USER_A, USER_B, USER_C, acting_as, auth_headers, org_world  # noqa: F401
from sqlalchemy.ext.asyncio import create_async_engine

from app.gateway import approval_adapters
from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.routers import approvals
from deerflow.approvals import InvalidPayloadError, validate_payload
from deerflow.persistence.approvals import PendingActionRepository
from deerflow.persistence.audit_events import AuditEventRepository
from deerflow.persistence.bootstrap import _get_alembic_config
from deerflow.tools.builtins.propose_action_tool import propose_action

SLACK = {"action_type": "slack_message", "title": "Tell the team", "target": "C123", "payload": {"text": "hello"}}
EMAIL = {"action_type": "email", "title": "Client update", "target": "client@example.com", "payload": {"subject": "Hi", "body": "Report attached"}}


class FakeSlack:
    def __init__(self, *, configured=True, fail=False):
        self._web_client = object() if configured else None
        self.sent = []
        self._fail = fail

    async def send(self, msg):
        if self._fail:
            raise RuntimeError("boom")
        self.sent.append(msg)


@pytest.fixture()
def slack(monkeypatch):
    channel = FakeSlack()
    monkeypatch.setattr("app.channels.service.get_channel_service", lambda: SimpleNamespace(get_channel=lambda name: channel if name == "slack" else None))
    return channel


def _app(session_factory) -> FastAPI:
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.state.pending_action_repo = PendingActionRepository(session_factory)
    app.state.audit_repo = AuditEventRepository(session_factory)
    app.include_router(approvals.router)
    return app


def _http(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _propose(session_factory, user=USER_A, **kw):
    return await PendingActionRepository(session_factory).create(**{**SLACK, **kw}, user_id=user)


# --- payload validation -----------------------------------------------------


def test_validate_payload_rejects_unsendable_proposals():
    validate_payload("slack_message", "C1", {"text": "x"})
    for bad in [("slack_message", "", {"text": "x"}), ("slack_message", "C1", {"text": " "}), ("email", "nope", {"subject": "a", "body": "b"}), ("email", "a@b.co", {"subject": "a"}), ("bogus", "x", {}), ("other", "x", "str")]:
        with pytest.raises(InvalidPayloadError):
            validate_payload(*bad)


# --- tenancy ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_other_user_and_org_cannot_see_or_touch(org_world, slack):  # noqa: F811
    row = await _propose(org_world)
    app = _app(org_world)
    async with _http(app) as client:
        assert (await client.get("/api/approvals", headers=auth_headers(USER_B))).json()["approvals"] == []
        assert (await client.get(f"/api/approvals/{row['id']}", headers=auth_headers(USER_B))).status_code == 404
        for verb in ("approve", "reject"):
            assert (await client.post(f"/api/approvals/{row['id']}/{verb}", headers=auth_headers(USER_B))).status_code == 404
        assert (await client.patch(f"/api/approvals/{row['id']}", json={"title": "x"}, headers=auth_headers(USER_B))).status_code == 404
        # A's own shared-workspace view does not leak private-org rows either.
        assert (await client.get("/api/approvals", headers=auth_headers(USER_A, ORG_S))).json()["approvals"] == []
    assert slack.sent == []
    assert (await PendingActionRepository(org_world).get(row["id"], user_id=USER_A))["status"] == "pending"


@pytest.mark.asyncio
async def test_shared_workspace_member_role_cannot_approve(org_world, slack):  # noqa: F811
    from datetime import UTC, datetime

    from deerflow.persistence.organizations.model import OrganizationMemberRow
    from deerflow.persistence.user.model import UserRow

    now = datetime.now(UTC)
    async with org_world() as session, session.begin():
        session.add(UserRow(id="plain", email="plain@example.com", password_hash=None, system_role="user", needs_setup=False, token_version=0, created_at=now))
        session.add(OrganizationMemberRow(organization_id=ORG_S, user_id="plain", role="member", status="active", created_at=now, updated_at=now))
    row = await _propose(org_world, user="storage-s")
    async with _http(_app(org_world)) as client:
        assert len((await client.get("/api/approvals", headers=auth_headers("plain", ORG_S))).json()["approvals"]) == 1
        assert (await client.post(f"/api/approvals/{row['id']}/approve", headers=auth_headers("plain", ORG_S))).status_code == 403
        assert (await client.post(f"/api/approvals/{row['id']}/approve", headers=auth_headers(USER_C, ORG_S))).status_code == 200
    assert len(slack.sent) == 1


# --- state machine + nothing before approval ---------------------------------


@pytest.mark.asyncio
async def test_nothing_executes_until_approved_then_exactly_once(org_world, slack):  # noqa: F811
    row = await _propose(org_world)
    assert slack.sent == []  # proposing never sends
    async with _http(_app(org_world)) as client:
        h = auth_headers(USER_A)
        assert (await client.get("/api/approvals?status=pending", headers=h)).json()["approvals"][0]["id"] == row["id"]
        done = (await client.post(f"/api/approvals/{row['id']}/approve", headers=h)).json()
        assert done["status"] == "executed" and done["decided_by"] == USER_A and done["executed_at"]
        assert (await client.post(f"/api/approvals/{row['id']}/approve", headers=h)).status_code == 409
        assert (await client.post(f"/api/approvals/{row['id']}/reject", headers=h)).status_code == 409
        assert (await client.patch(f"/api/approvals/{row['id']}", json={"title": "x"}, headers=h)).status_code == 409
    assert [m.text for m in slack.sent] == ["hello"]
    assert slack.sent[0].chat_id == "C123" and slack.sent[0].channel_name == "slack"


@pytest.mark.asyncio
async def test_reject_never_executes(org_world, slack):  # noqa: F811
    row = await _propose(org_world)
    async with _http(_app(org_world)) as client:
        h = auth_headers(USER_A)
        assert (await client.post(f"/api/approvals/{row['id']}/reject", headers=h)).json()["status"] == "rejected"
        assert (await client.post(f"/api/approvals/{row['id']}/approve", headers=h)).status_code == 409
    assert slack.sent == []


@pytest.mark.asyncio
async def test_edit_changes_what_gets_sent_and_keeps_original(org_world, slack):  # noqa: F811
    row = await _propose(org_world)
    async with _http(_app(org_world)) as client:
        h = auth_headers(USER_A)
        edited = await client.patch(f"/api/approvals/{row['id']}", json={"payload": {"text": "better words"}, "target": "C999"}, headers=h)
        assert edited.status_code == 200
        assert edited.json()["original_payload"] == {"text": "hello"}
        assert (await client.patch(f"/api/approvals/{row['id']}", json={"payload": {"text": ""}}, headers=h)).status_code == 422
        await client.post(f"/api/approvals/{row['id']}/approve", headers=h)
    assert [(m.chat_id, m.text) for m in slack.sent] == [("C999", "better words")]


@pytest.mark.asyncio
async def test_slack_not_configured_or_failing_marks_failed(org_world, monkeypatch):  # noqa: F811
    monkeypatch.setattr("app.channels.service.get_channel_service", lambda: None)
    row = await _propose(org_world)
    async with _http(_app(org_world)) as client:
        out = (await client.post(f"/api/approvals/{row['id']}/approve", headers=auth_headers(USER_A))).json()
    assert out["status"] == "failed" and "not configured" in out["error"]

    broken = FakeSlack(fail=True)
    monkeypatch.setattr("app.channels.service.get_channel_service", lambda: SimpleNamespace(get_channel=lambda name: broken))
    row = await _propose(org_world)
    async with _http(_app(org_world)) as client:
        out = (await client.post(f"/api/approvals/{row['id']}/approve", headers=auth_headers(USER_A))).json()
    assert out["status"] == "failed" and "boom" not in out["error"]


@pytest.mark.asyncio
async def test_email_and_ad_change_stay_ready_to_send_with_no_live_write(org_world, slack):  # noqa: F811
    email = await _propose(org_world, **EMAIL)
    ads = await _propose(org_world, action_type="ad_change", target="acct-1", payload={"change": "pause campaign 7"}, title="Pause")
    async with _http(_app(org_world)) as client:
        for row in (email, ads):
            out = (await client.post(f"/api/approvals/{row['id']}/approve", headers=auth_headers(USER_A))).json()
            assert out["status"] == "approved" and out["execution_result"]["state"] == "ready_to_send"
    assert slack.sent == []


@pytest.mark.asyncio
async def test_decisions_are_audited(org_world, slack):  # noqa: F811
    row = await _propose(org_world)
    async with _http(_app(org_world)) as client:
        await client.post(f"/api/approvals/{row['id']}/approve", headers=auth_headers(USER_A))
    events, _ = await AuditEventRepository(org_world).list(organization_id=None)
    assert {"approvals.approved", "approvals.executed"} <= {e["action"] for e in events}


@pytest.mark.asyncio
async def test_double_approve_race_executes_once(org_world, slack):  # noqa: F811
    import asyncio

    row = await _propose(org_world)
    async with _http(_app(org_world)) as client:
        h = auth_headers(USER_A)
        codes = sorted(r.status_code for r in await asyncio.gather(*[client.post(f"/api/approvals/{row['id']}/approve", headers=h) for _ in range(4)]))
    assert codes.count(200) == 1 and len(slack.sent) == 1


@pytest.mark.asyncio
async def test_adapter_registry_covers_every_type():
    from deerflow.approvals import ACTION_TYPES

    assert set(approval_adapters.ADAPTERS) == set(ACTION_TYPES)


# --- propose_action tool -----------------------------------------------------


@pytest.mark.asyncio
async def test_propose_action_tool_files_pending_row_and_sends_nothing(org_world, slack):  # noqa: F811
    runtime = SimpleNamespace(context={"user_id": USER_A, "thread_id": "t-1", "run_id": "r-1", "agent_name": "momo"}, config={})
    out = json.loads(await propose_action.coroutine(runtime=runtime, **SLACK))
    assert out["status"] == "pending_approval"
    with acting_as(USER_A):
        row = await PendingActionRepository(org_world).get(out["id"])
    assert (row["status"], row["thread_id"], row["run_id"], row["agent_name"]) == ("pending", "t-1", "r-1", "momo")
    assert slack.sent == []
    bad = await propose_action.coroutine(runtime=runtime, action_type="slack_message", title="t", target="", payload={"text": "x"})
    assert bad.startswith("Not filed")


@pytest.mark.asyncio
async def test_propose_action_tool_refuses_anonymous(org_world):  # noqa: F811
    from deerflow.runtime.user_context import reset_current_user, set_current_user

    token = set_current_user(None)  # conftest autouse installs a test user; this run has none
    try:
        runtime = SimpleNamespace(context={}, config={})
        out = await propose_action.coroutine(runtime=runtime, **SLACK)
    finally:
        reset_current_user(token)
    assert "authenticated" in out


# --- migration ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_migration_single_head_and_downgrade_roundtrip(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'm.db'}")
    cfg = _get_alembic_config(engine)
    try:
        assert len(ScriptDirectory.from_config(cfg).get_heads()) == 1
        import asyncio
        import sqlite3

        def tables():
            with sqlite3.connect(tmp_path / "m.db") as conn:
                return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

        await asyncio.to_thread(command.upgrade, cfg, "0049_pending_actions")
        assert "pending_actions" in tables()
        await asyncio.to_thread(command.downgrade, cfg, "0048_repair_audit_events")
        assert "pending_actions" not in tables()
        await asyncio.to_thread(command.upgrade, cfg, "head")
        assert "pending_actions" in tables()
    finally:
        await engine.dispose()
