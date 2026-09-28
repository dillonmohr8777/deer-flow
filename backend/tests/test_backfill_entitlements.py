"""Tests for scripts/backfill_entitlements.py (task f57, design §4 step 2).

Core logic is exercised directly against a real EntitlementRepository on
in-memory SQLite (mirrors how e6's own evaluator tests work), plus one
end-to-end ``run_backfill`` pass over multiple organizations and a thin
``main()`` argv-wiring check.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import scripts.backfill_entitlements as backfill
from deerflow.config.database_config import DatabaseConfig
from deerflow.config.entitlement_config import EntitlementConfig, EntitlementDefaultLimitsConfig
from deerflow.persistence.base import Base
from deerflow.persistence.entitlements import EntitlementRepository
from deerflow.persistence.organizations.model import OrganizationRow

ORG_A = "org-a"
ORG_B = "org-b"

NO_DEFAULTS = EntitlementDefaultLimitsConfig()
SOME_DEFAULTS = EntitlementDefaultLimitsConfig(projects_max=25, workflows_max=10)


@pytest_asyncio.fixture()
async def repo():
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield EntitlementRepository(session_factory), session_factory
    finally:
        await engine.dispose()


# -- backfill_organization ---------------------------------------------------


@pytest.mark.asyncio
async def test_creates_a_gate_row_for_every_minimum_set_key(repo):
    entitlement_repo, _ = repo
    created, skipped = await backfill.backfill_organization(entitlement_repo, ORG_A, NO_DEFAULTS, dry_run=False)

    assert created == len(backfill.GATE_KEYS)
    assert skipped == 0
    for key in backfill.GATE_KEYS:
        row = await entitlement_repo.get(ORG_A, key)
        assert row is not None
        assert row["status"] == "active"
        assert row["source"] == "manual"
        assert row["limit_value"] is None


@pytest.mark.asyncio
async def test_creates_a_limit_row_only_for_configured_defaults(repo):
    entitlement_repo, _ = repo
    created, _skipped = await backfill.backfill_organization(entitlement_repo, ORG_A, SOME_DEFAULTS, dry_run=False)

    # 5 gate keys + 2 configured limit keys (projects.max, workflows.max)
    assert created == len(backfill.GATE_KEYS) + 2
    projects_row = await entitlement_repo.get(ORG_A, "projects.max")
    assert projects_row["limit_value"] == 25
    workflows_row = await entitlement_repo.get(ORG_A, "workflows.max")
    assert workflows_row["limit_value"] == 10
    # Unconfigured limit keys are left alone -- no row, no guessed number.
    assert await entitlement_repo.get(ORG_A, "brands.max") is None
    assert await entitlement_repo.get(ORG_A, "repair_minutes.monthly") is None


@pytest.mark.asyncio
async def test_never_overwrites_an_existing_row(repo):
    entitlement_repo, _ = repo
    # A manual edit already suspended runs.create and set a custom limit.
    await entitlement_repo.upsert(ORG_A, "runs.create", source="manual", status="suspended")
    await entitlement_repo.upsert(ORG_A, "projects.max", limit_value=99, source="manual", status="active")

    created, skipped = await backfill.backfill_organization(entitlement_repo, ORG_A, SOME_DEFAULTS, dry_run=False)

    assert skipped == 2  # runs.create + projects.max both pre-existing
    assert created == len(backfill.GATE_KEYS) + 2 - 2
    runs_create = await entitlement_repo.get(ORG_A, "runs.create")
    assert runs_create["status"] == "suspended"  # untouched
    projects_row = await entitlement_repo.get(ORG_A, "projects.max")
    assert projects_row["limit_value"] == 99  # untouched, not reset to 25


@pytest.mark.asyncio
async def test_dry_run_writes_nothing(repo):
    entitlement_repo, _ = repo
    created, skipped = await backfill.backfill_organization(entitlement_repo, ORG_A, SOME_DEFAULTS, dry_run=True)

    assert created == len(backfill.GATE_KEYS) + 2
    assert skipped == 0
    assert await entitlement_repo.list_for_org(ORG_A) == []


# -- run_backfill: iterates every organization -------------------------------


@pytest_asyncio.fixture()
async def two_org_session_factory():
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        session.add(OrganizationRow(id=ORG_A, slug="org-a", name="Org A", status="active"))
        session.add(OrganizationRow(id=ORG_B, slug="org-b", name="Org B", status="active"))
        await session.commit()
    try:
        yield session_factory
    finally:
        await engine.dispose()


def _config(default_limits: EntitlementDefaultLimitsConfig) -> SimpleNamespace:
    return SimpleNamespace(
        entitlements=EntitlementConfig(default_limits=default_limits),
        database=DatabaseConfig(backend="memory"),
    )


@pytest.mark.asyncio
async def test_run_backfill_seeds_rows_for_every_organization(two_org_session_factory):
    config = _config(SOME_DEFAULTS)
    result = await backfill.run_backfill(config, dry_run=False, session_factory=two_org_session_factory)

    assert result == 0
    entitlement_repo = EntitlementRepository(two_org_session_factory)
    for org_id in (ORG_A, ORG_B):
        rows = await entitlement_repo.list_for_org(org_id)
        keys = {r["key"] for r in rows}
        assert keys == {*backfill.GATE_KEYS, "projects.max", "workflows.max"}


@pytest.mark.asyncio
async def test_run_backfill_is_idempotent_across_runs(two_org_session_factory):
    config = _config(SOME_DEFAULTS)
    await backfill.run_backfill(config, dry_run=False, session_factory=two_org_session_factory)
    await backfill.run_backfill(config, dry_run=False, session_factory=two_org_session_factory)

    entitlement_repo = EntitlementRepository(two_org_session_factory)
    rows_a = await entitlement_repo.list_for_org(ORG_A)
    assert len(rows_a) == len(backfill.GATE_KEYS) + 2  # not doubled


@pytest.mark.asyncio
async def test_run_backfill_refuses_when_no_organizations_found():
    """Review finding (f63): zero orgs almost always means "pointed at the
    wrong database", not "nothing to do" -- a silent 0 return let a dry run
    from the wrong working directory look like success."""
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        config = _config(NO_DEFAULTS)
        result = await backfill.run_backfill(config, dry_run=False, session_factory=session_factory)
        assert result == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_run_backfill_returns_1_for_an_unsupported_backend():
    config = _config(NO_DEFAULTS)  # database=DatabaseConfig(backend="memory")
    result = await backfill.run_backfill(config, dry_run=False, session_factory=None)
    assert result == 1


# -- run_backfill without an injected session_factory: the real connection
# path (review finding f63: --dry-run must never migrate the schema) --------


@pytest.mark.asyncio
async def test_dry_run_against_an_unbootstrapped_database_refuses_and_creates_nothing(tmp_path):
    """Reproduces the review's exact repro: pointing --dry-run at a sqlite
    dir that doesn't exist (or was never bootstrapped by the Gateway) must
    refuse, not silently create the database and report success."""
    sqlite_dir = tmp_path / "does-not-exist-yet"
    config = SimpleNamespace(
        entitlements=EntitlementConfig(default_limits=NO_DEFAULTS),
        database=DatabaseConfig(backend="sqlite", sqlite_dir=str(sqlite_dir)),
    )

    result = await backfill.run_backfill(config, dry_run=True, session_factory=None)

    assert result == 1
    assert not sqlite_dir.exists()  # never created -- the bug's exact symptom


async def _bootstrap_sqlite_at_head(sqlite_dir) -> None:
    from alembic import command

    from deerflow.persistence.bootstrap import _get_alembic_config

    sqlite_dir.mkdir(parents=True, exist_ok=True)
    engine = create_async_engine(f"sqlite+aiosqlite:///{sqlite_dir / 'deerflow.db'}")
    try:
        import asyncio

        await asyncio.to_thread(command.upgrade, _get_alembic_config(engine), "head")
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_dry_run_against_a_bootstrapped_database_succeeds_and_writes_nothing(tmp_path):
    sqlite_dir = tmp_path / "already-bootstrapped"
    await _bootstrap_sqlite_at_head(sqlite_dir)

    engine = create_async_engine(f"sqlite+aiosqlite:///{sqlite_dir / 'deerflow.db'}")
    try:
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            session.add(OrganizationRow(id=ORG_A, slug="org-a", name="Org A", status="active"))
            await session.commit()
    finally:
        await engine.dispose()

    config = SimpleNamespace(
        entitlements=EntitlementConfig(default_limits=SOME_DEFAULTS),
        database=DatabaseConfig(backend="sqlite", sqlite_dir=str(sqlite_dir)),
    )

    result = await backfill.run_backfill(config, dry_run=True, session_factory=None)
    assert result == 0

    verify_engine = create_async_engine(f"sqlite+aiosqlite:///{sqlite_dir / 'deerflow.db'}")
    try:
        entitlement_repo = EntitlementRepository(async_sessionmaker(verify_engine, expire_on_commit=False))
        assert await entitlement_repo.list_for_org(ORG_A) == []  # dry-run wrote nothing
    finally:
        await verify_engine.dispose()


@pytest.mark.asyncio
async def test_real_run_against_a_bootstrapped_database_writes_rows(tmp_path):
    sqlite_dir = tmp_path / "already-bootstrapped"
    await _bootstrap_sqlite_at_head(sqlite_dir)

    engine = create_async_engine(f"sqlite+aiosqlite:///{sqlite_dir / 'deerflow.db'}")
    try:
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            session.add(OrganizationRow(id=ORG_A, slug="org-a", name="Org A", status="active"))
            await session.commit()
    finally:
        await engine.dispose()

    config = SimpleNamespace(
        entitlements=EntitlementConfig(default_limits=NO_DEFAULTS),
        database=DatabaseConfig(backend="sqlite", sqlite_dir=str(sqlite_dir)),
    )

    result = await backfill.run_backfill(config, dry_run=False, session_factory=None)
    assert result == 0

    verify_engine = create_async_engine(f"sqlite+aiosqlite:///{sqlite_dir / 'deerflow.db'}")
    try:
        entitlement_repo = EntitlementRepository(async_sessionmaker(verify_engine, expire_on_commit=False))
        rows = await entitlement_repo.list_for_org(ORG_A)
        assert {r["key"] for r in rows} == set(backfill.GATE_KEYS)
    finally:
        await verify_engine.dispose()


# -- main(): argv wiring ------------------------------------------------------


def test_main_parses_dry_run_flag(monkeypatch):
    calls: list[dict] = []

    async def _fake_run_backfill(config, *, dry_run, session_factory=None):  # noqa: ARG001
        calls.append({"dry_run": dry_run})
        return 0

    monkeypatch.setattr(backfill, "get_app_config", lambda: _config(NO_DEFAULTS))
    monkeypatch.setattr(backfill, "run_backfill", _fake_run_backfill)
    monkeypatch.setattr("sys.argv", ["backfill_entitlements", "--dry-run"])

    assert backfill.main() == 0
    assert calls == [{"dry_run": True}]


def test_main_defaults_dry_run_to_false(monkeypatch):
    calls: list[dict] = []

    async def _fake_run_backfill(config, *, dry_run, session_factory=None):  # noqa: ARG001
        calls.append({"dry_run": dry_run})
        return 0

    monkeypatch.setattr(backfill, "get_app_config", lambda: _config(NO_DEFAULTS))
    monkeypatch.setattr(backfill, "run_backfill", _fake_run_backfill)
    monkeypatch.setattr("sys.argv", ["backfill_entitlements"])

    assert backfill.main() == 0
    assert calls == [{"dry_run": False}]
