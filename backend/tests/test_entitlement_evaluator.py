"""Core evaluator tests for the M4 entitlement gate (task e6).

Covers design §6's acceptance bar (allowed/denied/missing for a gate key and
a limit key) plus the degraded-provider grace-period path (§3), against a
real ``EntitlementRepository`` on in-memory SQLite -- mirrors how e5/b6/b7
test their repositories.
"""

from __future__ import annotations

import time

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from deerflow.authz.entitlements import evaluate_entitlement, reset_entitlement_cache
from deerflow.config.entitlement_config import EntitlementConfig
from deerflow.persistence.base import Base
from deerflow.persistence.entitlements import EntitlementRepository

pytestmark = pytest.mark.asyncio

ORG_A = "org-a"
ORG_B = "org-b"
ENABLED = EntitlementConfig(enabled=True, grace_period_seconds=60)


@pytest.fixture(autouse=True)
def _reset_cache():
    reset_entitlement_cache()
    yield
    reset_entitlement_cache()


@pytest_asyncio.fixture()
async def repo():
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    yield EntitlementRepository(session_factory)
    await engine.dispose()


class _FlakyRepo:
    """Wraps a real repo, raising on every call once armed."""

    def __init__(self, inner: EntitlementRepository) -> None:
        self._inner = inner
        self.raise_next = False

    async def list_for_org(self, organization_id: str) -> list[dict]:
        if self.raise_next:
            raise RuntimeError("provider unavailable")
        return await self._inner.list_for_org(organization_id)


# ---------------------------------------------------------------------------
# Disabled config: always allow (today's behavior, unchanged)
# ---------------------------------------------------------------------------


async def test_disabled_config_always_allows(repo):
    decision = await evaluate_entitlement(repo, None, "runs.create", config=EntitlementConfig(enabled=False))
    assert decision.allowed is True


# ---------------------------------------------------------------------------
# Gate key: runs.create — allowed / denied (suspended) / missing
# ---------------------------------------------------------------------------


async def test_gate_key_allowed_with_active_row(repo):
    await repo.upsert(ORG_A, "runs.create", status="active")
    decision = await evaluate_entitlement(repo, ORG_A, "runs.create", config=ENABLED)
    assert decision.allowed is True
    assert decision.reason is None


async def test_gate_key_denied_with_suspended_row(repo):
    await repo.upsert(ORG_A, "runs.create", status="suspended")
    decision = await evaluate_entitlement(repo, ORG_A, "runs.create", config=ENABLED)
    assert decision.allowed is False
    assert decision.reason == "suspended"


async def test_gate_key_denied_with_no_row(repo):
    decision = await evaluate_entitlement(repo, ORG_A, "runs.create", config=ENABLED)
    assert decision.allowed is False
    assert decision.reason == "no_row"


async def test_gate_key_denied_with_unresolved_organization(repo):
    decision = await evaluate_entitlement(repo, None, "runs.create", config=ENABLED)
    assert decision.allowed is False
    assert decision.reason == "no_organization"


# ---------------------------------------------------------------------------
# Gate key: agents.manage — same four cases
# ---------------------------------------------------------------------------


async def test_agents_manage_allowed_with_active_row(repo):
    await repo.upsert(ORG_A, "agents.manage", status="active")
    decision = await evaluate_entitlement(repo, ORG_A, "agents.manage", config=ENABLED)
    assert decision.allowed is True


async def test_agents_manage_denied_with_suspended_row(repo):
    await repo.upsert(ORG_A, "agents.manage", status="suspended")
    decision = await evaluate_entitlement(repo, ORG_A, "agents.manage", config=ENABLED)
    assert decision.allowed is False
    assert decision.reason == "suspended"


async def test_agents_manage_denied_with_no_row(repo):
    decision = await evaluate_entitlement(repo, ORG_A, "agents.manage", config=ENABLED)
    assert decision.allowed is False
    assert decision.reason == "no_row"


async def test_agents_manage_denied_with_unresolved_organization(repo):
    decision = await evaluate_entitlement(repo, None, "agents.manage", config=ENABLED)
    assert decision.allowed is False
    assert decision.reason == "no_organization"


# ---------------------------------------------------------------------------
# Limit key: projects.max — under / at / missing
# ---------------------------------------------------------------------------


async def test_limit_key_allowed_under_limit(repo):
    await repo.upsert(ORG_A, "projects.max", limit_value=25, status="active")
    decision = await evaluate_entitlement(repo, ORG_A, "projects.max", current_usage=4, config=ENABLED)
    assert decision.allowed is True
    assert decision.limit == 25
    assert decision.used == 4


async def test_limit_key_denied_at_limit(repo):
    await repo.upsert(ORG_A, "projects.max", limit_value=5, status="active")
    decision = await evaluate_entitlement(repo, ORG_A, "projects.max", current_usage=5, config=ENABLED)
    assert decision.allowed is False
    assert decision.reason == "limit_exceeded"
    assert decision.limit == 5
    assert decision.used == 5


async def test_limit_key_missing_row_treated_as_zero(repo):
    decision = await evaluate_entitlement(repo, ORG_A, "projects.max", current_usage=0, config=ENABLED)
    assert decision.allowed is False
    assert decision.limit == 0
    assert decision.reason == "limit_exceeded"


# ---------------------------------------------------------------------------
# Degraded provider: process-level cache across multiple requests
# ---------------------------------------------------------------------------


async def test_degraded_provider_serves_cached_snapshot_across_requests(repo, monkeypatch):
    await repo.upsert(ORG_A, "runs.create", status="active")
    flaky = _FlakyRepo(repo)

    # First read succeeds and populates the process-level cache.
    first = await evaluate_entitlement(flaky, ORG_A, "runs.create", config=ENABLED)
    assert first.allowed is True
    assert first.degraded is False

    # Provider starts failing. Multiple *separate* calls (not one call
    # reused within a request) must still be served from the cache -- this
    # is the point of a process-level cache rather than a per-request one.
    flaky.raise_next = True
    second = await evaluate_entitlement(flaky, ORG_A, "runs.create", config=ENABLED)
    third = await evaluate_entitlement(flaky, ORG_A, "runs.create", config=ENABLED)
    assert second.allowed is True
    assert second.degraded is True
    assert third.allowed is True
    assert third.degraded is True


async def test_degraded_provider_fails_closed_after_grace_period(repo, monkeypatch):
    await repo.upsert(ORG_A, "runs.create", status="active")
    flaky = _FlakyRepo(repo)
    short_grace = EntitlementConfig(enabled=True, grace_period_seconds=1)

    first = await evaluate_entitlement(flaky, ORG_A, "runs.create", config=short_grace)
    assert first.allowed is True

    flaky.raise_next = True
    real_monotonic = time.monotonic
    monkeypatch.setattr(time, "monotonic", lambda: real_monotonic() + 1000)
    decision = await evaluate_entitlement(flaky, ORG_A, "runs.create", config=short_grace)
    assert decision.allowed is False
    assert decision.degraded is True
    assert decision.reason == "provider_error"


async def test_degraded_provider_console_read_stays_allowed_after_grace_period(repo, monkeypatch):
    await repo.upsert(ORG_A, "console.read", status="active")
    flaky = _FlakyRepo(repo)
    short_grace = EntitlementConfig(enabled=True, grace_period_seconds=1)

    first = await evaluate_entitlement(flaky, ORG_A, "console.read", config=short_grace)
    assert first.allowed is True

    flaky.raise_next = True
    real_monotonic = time.monotonic
    monkeypatch.setattr(time, "monotonic", lambda: real_monotonic() + 1000)
    decision = await evaluate_entitlement(flaky, ORG_A, "console.read", config=short_grace)
    assert decision.allowed is True
    assert decision.degraded is True


async def test_degraded_provider_with_no_prior_read_fails_closed(repo):
    flaky = _FlakyRepo(repo)
    flaky.raise_next = True
    decision = await evaluate_entitlement(flaky, ORG_A, "runs.create", config=ENABLED)
    assert decision.allowed is False
    assert decision.degraded is True
    assert decision.reason == "provider_error"


async def test_degraded_provider_cache_does_not_leak_between_organizations(repo):
    """Review finding: the process-level cache is keyed per organization_id --
    org B's snapshot must never answer for org A once org A's own provider
    read fails. Populate the two orgs differently, warm both caches, then
    degrade only org A and assert its decision still reflects its own
    (suspended) row, never org B's (active) one."""
    await repo.upsert(ORG_A, "runs.create", status="suspended")
    await repo.upsert(ORG_B, "runs.create", status="active")

    flaky_a = _FlakyRepo(repo)
    flaky_b = _FlakyRepo(repo)
    warm_a = await evaluate_entitlement(flaky_a, ORG_A, "runs.create", config=ENABLED)
    warm_b = await evaluate_entitlement(flaky_b, ORG_B, "runs.create", config=ENABLED)
    assert warm_a.allowed is False
    assert warm_b.allowed is True

    flaky_a.raise_next = True
    degraded_a = await evaluate_entitlement(flaky_a, ORG_A, "runs.create", config=ENABLED)
    assert degraded_a.degraded is True
    assert degraded_a.allowed is False  # org A's own cached row is suspended, never org B's active one


async def test_degraded_provider_allows_when_fail_closed_is_false(repo, monkeypatch):
    """Review finding: EntitlementConfig.fail_closed was accepted but never
    read. An operator who sets it False wants the gate to degrade open
    (through an outage) rather than lock every org out."""
    degrade_open = EntitlementConfig(enabled=True, fail_closed=False, grace_period_seconds=1)
    await repo.upsert(ORG_A, "runs.create", status="active")
    flaky = _FlakyRepo(repo)

    first = await evaluate_entitlement(flaky, ORG_A, "runs.create", config=degrade_open)
    assert first.allowed is True

    flaky.raise_next = True
    real_monotonic = time.monotonic
    monkeypatch.setattr(time, "monotonic", lambda: real_monotonic() + 1000)
    decision = await evaluate_entitlement(flaky, ORG_A, "runs.create", config=degrade_open)
    assert decision.allowed is True
    assert decision.degraded is True


async def test_degraded_provider_with_no_prior_read_allows_when_fail_closed_is_false(repo):
    degrade_open = EntitlementConfig(enabled=True, fail_closed=False)
    flaky = _FlakyRepo(repo)
    flaky.raise_next = True
    decision = await evaluate_entitlement(flaky, ORG_A, "runs.create", config=degrade_open)
    assert decision.allowed is True
    assert decision.degraded is True


# ---------------------------------------------------------------------------
# Isolation: org A never sees org B's rows
# ---------------------------------------------------------------------------


async def test_repository_never_leaks_another_organizations_rows(repo):
    await repo.upsert(ORG_A, "runs.create", status="active")
    await repo.upsert(ORG_B, "runs.create", status="suspended")

    a_row = await repo.get(ORG_A, "runs.create")
    b_row = await repo.get(ORG_B, "runs.create")
    assert a_row["status"] == "active"
    assert b_row["status"] == "suspended"

    a_rows = await repo.list_for_org(ORG_A)
    assert all(r["organization_id"] == ORG_A for r in a_rows)
    assert not any(r["key"] == "runs.create" and r["status"] == "suspended" for r in a_rows)

    a_decision = await evaluate_entitlement(repo, ORG_A, "runs.create", config=ENABLED)
    b_decision = await evaluate_entitlement(repo, ORG_B, "runs.create", config=ENABLED)
    assert a_decision.allowed is True
    assert b_decision.allowed is False
