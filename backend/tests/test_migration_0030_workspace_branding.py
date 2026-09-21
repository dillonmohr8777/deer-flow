"""Migration and registry checks for 0030_workspace_branding.

Two separate concerns, deliberately kept apart:

1. ``organization_branding`` must reach ``Base.metadata`` through the model
   registry, NOT through importing the branding module or the gateway router.
   The router import masks this in the running app (``app.py`` imports routers
   at module scope, before the lifespan runs bootstrap), but ``migrations/env.py``
   and ``_env_filters.py`` import only ``deerflow.persistence.models`` — so an
   unregistered model is invisible to autogenerate, and bootstrap's empty-DB
   path would ``create_all`` without the table and then stamp head, leaving it
   permanently missing. The registry check therefore runs in a **fresh
   subprocess** that never imports the branding module.

2. The migration itself upgrades and downgrades on a disposable SQLite database
   at 0029, preserving the tables and rows that already existed.

Reuses the machinery in ``test_migration_0017_personal_access_tokens.py``.
No dependency is installed and no live database is touched.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import textwrap
from datetime import UTC, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from sqlalchemy.ext.asyncio import create_async_engine

from deerflow.persistence.bootstrap import _MIGRATIONS_DIR

_SCRIPT_LOCATION = str(_MIGRATIONS_DIR)
_REVISION = "0030_workspace_branding"
_PREVIOUS = "0029_shared_workspace"
_TABLE = "organization_branding"

_EXPECTED_COLUMNS = {
    "organization_id",
    "brand_name",
    "logo_data_uri",
    "treatment",
    "version",
    "updated_by",
    "created_at",
    "updated_at",
}


def _alembic_config(db_url: str) -> AlembicConfig:
    cfg = AlembicConfig()
    cfg.set_main_option("script_location", _SCRIPT_LOCATION)
    # Escape % for ConfigParser (SQLite URLs carry none, Postgres passwords might).
    cfg.set_main_option("sqlalchemy.url", db_url.replace("%", "%%"))
    return cfg


def _table_names(sync_conn) -> set[str]:
    return set(sa.inspect(sync_conn).get_table_names())


def _column_names(sync_conn, table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(sync_conn).get_columns(table)}


async def _inspect(engine, fn):
    async with engine.connect() as conn:
        return await conn.run_sync(fn)


def test_branding_model_is_registered_without_importing_it() -> None:
    """The registry alone must register the table, in a process that never
    imports the branding module or the gateway router.

    Importing ``deerflow.persistence.organizations.branding`` directly — which
    the branding tests do — would register the table and mask a missing entry
    in ``persistence/models/__init__.py``. A subprocess keeps this honest.
    """
    backend = Path(__file__).resolve().parents[1]
    script = textwrap.dedent(
        """
        import sys
        sys.dont_write_bytecode = True
        import deerflow.persistence.models  # the registry, and nothing else
        from deerflow.persistence.base import Base

        tables = set(Base.metadata.tables)
        missing = {"organizations", "organization_members", "organization_branding"} - tables
        if missing:
            print("MISSING:" + ",".join(sorted(missing)))
            raise SystemExit(1)
        print("OK")
        """
    )
    env = dict(os.environ)
    # Mirror the pinning this suite runs under; the child must resolve the same
    # harness, and must NOT inherit an import of the branding module.
    env["PYTHONPATH"] = os.pathsep.join([str(backend), str(backend / "packages" / "extension-api"), str(backend / "packages" / "harness")])
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(  # noqa: S603 - fixed interpreter and inline script
        [sys.executable, "-c", script],
        cwd=str(backend),
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
    )
    assert result.returncode == 0, f"registry check failed: {result.stdout}{result.stderr}"
    assert "OK" in result.stdout


@pytest.mark.asyncio
async def test_branding_migration_upgrade_downgrade_preserves_prior_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "branding-migration.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    engine = create_async_engine(url)
    cfg = _alembic_config(url)
    try:
        # Alembic's env.py drives migrations with its own asyncio.run, so the
        # sync command API must run off the test loop.
        await asyncio.to_thread(alembic_command.upgrade, cfg, _PREVIOUS)

        at_0029 = await _inspect(engine, _table_names)
        assert _TABLE not in at_0029, "0029 must not already contain the branding table"
        assert {"organizations", "organization_members", "workspace_invitations"} <= at_0029

        # Seed a shared workspace so the upgrade is exercised against real rows.
        now = datetime.now(UTC)
        async with engine.begin() as conn:
            await conn.execute(
                sa.text("INSERT INTO organizations (id, slug, name, status, storage_user_id, created_at, updated_at) VALUES ('ws-1', 'momentum', 'Momentum', 'active', 'storage-owner', :now, :now)"),
                {"now": now},
            )
            await conn.execute(
                sa.text("INSERT INTO organization_members (organization_id, user_id, role, status, created_at, updated_at) VALUES ('ws-1', 'actor-a', 'owner', 'active', :now, :now)"),
                {"now": now},
            )

        await asyncio.to_thread(alembic_command.upgrade, cfg, _REVISION)

        after_up = await _inspect(engine, _table_names)
        assert _TABLE in after_up
        # Additive: every table present at 0029 survives.
        assert at_0029 <= after_up, f"upgrade dropped tables: {at_0029 - after_up}"
        assert await _inspect(engine, lambda c: _column_names(c, _TABLE)) == _EXPECTED_COLUMNS

        async with engine.connect() as conn:
            preserved = (await conn.execute(sa.text("SELECT name, storage_user_id FROM organizations WHERE id='ws-1'"))).one()
            assert preserved == ("Momentum", "storage-owner")
            members = (await conn.execute(sa.text("SELECT COUNT(*) FROM organization_members"))).scalar_one()
            assert members == 1
            # The new table starts empty; no backfill is attempted.
            assert (await conn.execute(sa.text(f"SELECT COUNT(*) FROM {_TABLE}"))).scalar_one() == 0

        # A branding row round-trips through the migrated schema. created_at
        # and updated_at are NOT NULL with only a client-side (ORM) default,
        # so a raw INSERT -- unlike the real OrganizationBrandingRow path --
        # must supply them explicitly.
        async with engine.begin() as conn:
            await conn.execute(
                sa.text(
                    f"INSERT INTO {_TABLE} (organization_id, brand_name, treatment, version, created_at, updated_at) "
                    "VALUES ('ws-1', 'Momentum 360', 'paper', 1, :now, :now)"
                ),
                {"now": datetime.now(UTC)},
            )
        async with engine.connect() as conn:
            stored = (await conn.execute(sa.text(f"SELECT brand_name, treatment, version FROM {_TABLE}"))).one()
            assert stored == ("Momentum 360", "paper", 1)

        # Downgrade drops exactly this table and leaves 0029's schema and rows.
        await asyncio.to_thread(alembic_command.downgrade, cfg, _PREVIOUS)
        after_down = await _inspect(engine, _table_names)
        assert _TABLE not in after_down
        assert at_0029 <= after_down, f"downgrade dropped prior tables: {at_0029 - after_down}"
        async with engine.connect() as conn:
            still_there = (await conn.execute(sa.text("SELECT name FROM organizations WHERE id='ws-1'"))).scalar_one()
            assert still_there == "Momentum"

        # Round trip is idempotent.
        await asyncio.to_thread(alembic_command.upgrade, cfg, _REVISION)
        assert _TABLE in await _inspect(engine, _table_names)
    finally:
        await engine.dispose()
