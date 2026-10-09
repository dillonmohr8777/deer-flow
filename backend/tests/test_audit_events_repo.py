"""AuditEventRepository: record/list, redaction, and never-raises."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from deerflow.persistence.audit_events import AuditEventRepository, AuditEventRow, redact_audit_details
from deerflow.persistence.base import Base

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture()
async def repo():
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=[AuditEventRow.__table__]))
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    yield AuditEventRepository(session_factory)
    await engine.dispose()


# ── redact_audit_details ────────────────────────────────────────────────────


def test_redact_blanks_secret_shaped_keys():
    raw = {"password": "hunter2", "api_key": "sk-abc", "nested": {"cookie": "a=b"}, "list": [{"token": "t"}], "name": "ok"}
    redacted = redact_audit_details(raw)
    assert redacted["password"] == "[redacted]"
    assert redacted["api_key"] == "[redacted]"
    assert redacted["nested"]["cookie"] == "[redacted]"
    assert redacted["list"][0]["token"] == "[redacted]"
    assert redacted["name"] == "ok"


def test_redact_passes_through_non_dict_values():
    assert redact_audit_details("plain string") == "plain string"
    assert redact_audit_details(None) is None
    assert redact_audit_details([1, 2, 3]) == [1, 2, 3]


# ── record / list ────────────────────────────────────────────────────────


async def test_record_redacts_details_before_persisting(repo: AuditEventRepository):
    await repo.record(action="auth.pat.created", outcome="success", actor_user_id="u1", organization_id="org1", details={"name": "ci", "token": "dfp_should_not_persist"})
    events, _ = await repo.list(organization_id="org1")
    assert len(events) == 1
    assert events[0]["details"]["token"] == "[redacted]"
    assert events[0]["details"]["name"] == "ci"


async def test_record_never_raises_on_persistence_failure():
    class _BrokenSessionFactory:
        def __call__(self):
            raise RuntimeError("db unavailable")

    repo = AuditEventRepository(_BrokenSessionFactory())
    # Must not raise -- the audited action must not fail because logging it did.
    await repo.record(action="auth.login.succeeded", outcome="success", actor_user_id="u1")


async def test_list_filters_by_organization_action_prefix_and_actor(repo: AuditEventRepository):
    await repo.record(action="auth.login.succeeded", outcome="success", actor_user_id="u1", organization_id="org1")
    await repo.record(action="auth.login.failed", outcome="denied", actor_user_id=None, organization_id="org1")
    await repo.record(action="mcp.config.updated", outcome="success", actor_user_id="u2", organization_id="org1")
    await repo.record(action="auth.login.succeeded", outcome="success", actor_user_id="u1", organization_id="org2")

    org1_events, _ = await repo.list(organization_id="org1")
    assert len(org1_events) == 3

    login_events, _ = await repo.list(organization_id="org1", action_prefix="auth.login.")
    assert {e["action"] for e in login_events} == {"auth.login.succeeded", "auth.login.failed"}

    u2_events, _ = await repo.list(organization_id="org1", actor_user_id="u2")
    assert len(u2_events) == 1
    assert u2_events[0]["action"] == "mcp.config.updated"

    all_events, _ = await repo.list(organization_id=None)
    assert len(all_events) == 4


async def test_list_filters_by_since_and_until(repo: AuditEventRepository):
    await repo.record(action="a.old", outcome="success")
    events_before, _ = await repo.list(organization_id=None)
    old_occurred_at = datetime.fromisoformat(events_before[0]["occurred_at"])

    await repo.record(action="a.new", outcome="success")

    since_cutoff = old_occurred_at + timedelta(milliseconds=1)
    recent, _ = await repo.list(organization_id=None, since=since_cutoff)
    assert [e["action"] for e in recent] == ["a.new"]

    until_cutoff = old_occurred_at
    older, _ = await repo.list(organization_id=None, until=until_cutoff)
    assert [e["action"] for e in older] == ["a.old"]


async def test_list_cursor_pagination_covers_every_row_exactly_once(repo: AuditEventRepository):
    for i in range(5):
        await repo.record(action=f"a.event{i}", outcome="success")

    seen: list[str] = []
    cursor = None
    for _ in range(10):
        page, cursor = await repo.list(organization_id=None, limit=2, cursor=cursor)
        seen.extend(event["action"] for event in page)
        if cursor is None:
            break

    assert len(seen) == 5
    assert len(set(seen)) == 5


async def test_record_defaults_occurred_at_to_now(repo: AuditEventRepository):
    before = datetime.now(UTC)
    await repo.record(action="auth.logout", outcome="success", actor_user_id="u1")
    events, _ = await repo.list(organization_id=None)
    occurred_at = datetime.fromisoformat(events[0]["occurred_at"])
    assert occurred_at >= before - timedelta(seconds=5)
