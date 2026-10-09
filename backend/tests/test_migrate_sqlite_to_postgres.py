"""Tests for scripts/migrate_sqlite_to_postgres.py.

Offline tests use a small synthetic SQLite database as both source and
(standing in for Postgres) target -- every code path except the
PostgreSQL-only sequence reset runs identically against either dialect. The
one live test below exercises that Postgres-only path for real, gated by
``TEST_POSTGRES_URI`` like the rest of this repo's live-Postgres tests.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url

from deerflow.persistence.projects.model import ProjectDocumentRow, ProjectRow
from deerflow.persistence.run.model import RunChangeClockRow
from deerflow.persistence.user.model import UserRow
from scripts.migrate_sqlite_to_postgres import (
    TableReport,
    build_pg_url,
    is_target_empty,
    main,
    reset_sequences,
    run_alembic_upgrade,
)
from scripts.migrate_sqlite_to_postgres import (
    _print_report as print_report,
)

POSTGRES_URL = os.environ.get("TEST_POSTGRES_URI")


def _seed_source(sqlite_path: Path) -> None:
    """Bring *sqlite_path* to alembic head and insert one row per seeded table."""
    run_alembic_upgrade(make_url(f"sqlite:///{sqlite_path}"))
    engine = create_engine(f"sqlite:///{sqlite_path}")
    try:
        with engine.begin() as conn:
            conn.execute(UserRow.__table__.insert(), {"id": "u1", "email": "a@example.com"})
            conn.execute(ProjectRow.__table__.insert(), {"id": "p1", "user_id": "u1", "name": "Proj"})
            conn.execute(
                ProjectDocumentRow.__table__.insert(),
                {
                    "id": "d1",
                    "project_id": "p1",
                    "user_id": "u1",
                    "name": "doc.txt",
                    "stored_relpath": "u1/p1/d1",
                    "sha256": "ab" * 32,
                    "size_bytes": 3,
                },
            )
            conn.execute(RunChangeClockRow.__table__.insert(), {"id": 1, "value": 5})
    finally:
        engine.dispose()


def test_build_pg_url_normalizes_driver():
    assert build_pg_url("postgresql://u:p@h/db").drivername == "postgresql+psycopg"
    assert build_pg_url("postgres://u:p@h/db").drivername == "postgresql+psycopg"
    assert build_pg_url("postgresql+asyncpg://u:p@h/db").drivername == "postgresql+asyncpg"


def test_is_target_empty(tmp_path):
    empty = create_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    try:
        assert is_target_empty(empty) is True
    finally:
        empty.dispose()

    populated_path = tmp_path / "populated.db"
    run_alembic_upgrade(make_url(f"sqlite:///{populated_path}"))
    populated = create_engine(f"sqlite:///{populated_path}")
    try:
        assert is_target_empty(populated) is False
    finally:
        populated.dispose()


def test_print_report_flags_mismatch(capsys):
    assert print_report([TableReport("t", 3, 3)]) is True
    assert print_report([TableReport("t", 3, 2)]) is False
    capsys.readouterr()


def test_main_copies_every_row_between_two_sqlite_databases(tmp_path):
    source = tmp_path / "source.db"
    target = tmp_path / "target.db"
    _seed_source(source)

    rc = main([str(source), f"sqlite:///{target}"])
    assert rc == 0

    engine = create_engine(f"sqlite:///{target}")
    try:
        with engine.connect() as conn:
            users = conn.execute(select(UserRow.__table__)).mappings().all()
            docs = conn.execute(select(ProjectDocumentRow.__table__)).mappings().all()
            clock = conn.execute(select(RunChangeClockRow.__table__)).mappings().all()
    finally:
        engine.dispose()
    assert [u["email"] for u in users] == ["a@example.com"]
    assert docs[0]["sha256"] == "ab" * 32
    assert docs[0]["size_bytes"] == 3
    assert clock[0]["value"] == 5


def test_main_refuses_nonempty_target_without_force(tmp_path):
    source = tmp_path / "source.db"
    target = tmp_path / "target.db"
    _seed_source(source)
    run_alembic_upgrade(make_url(f"sqlite:///{target}"))  # target already has tables

    rc = main([str(source), f"sqlite:///{target}"])
    assert rc == 2


def test_main_force_recopies_over_stale_target(tmp_path):
    source = tmp_path / "source.db"
    target = tmp_path / "target.db"
    _seed_source(source)
    _seed_source(target)  # stale copy already sitting at the same primary keys

    rc = main([str(source), f"sqlite:///{target}", "--force"])
    assert rc == 0

    engine = create_engine(f"sqlite:///{target}")
    try:
        with engine.connect() as conn:
            users = conn.execute(select(UserRow.__table__)).mappings().all()
    finally:
        engine.dispose()
    assert len(users) == 1  # not duplicated by the delete-then-copy pass


def test_main_refuses_missing_sqlite_file(tmp_path):
    with pytest.raises(SystemExit):
        main([str(tmp_path / "does-not-exist.db"), f"sqlite:///{tmp_path / 't.db'}"])


def test_reset_sequences_noop_for_non_postgres(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'x.db'}")
    try:
        reset_sequences(engine)  # must not raise for a non-postgres dialect
    finally:
        engine.dispose()


@pytest.mark.skipif(not POSTGRES_URL, reason="set TEST_POSTGRES_URI to run the live PostgreSQL migration test")
def test_migrate_against_real_postgres(tmp_path):
    from deerflow.persistence.postgres_schema import dsn_with_search_path, ensure_postgres_schema

    source = tmp_path / "source.db"
    _seed_source(source)

    assert POSTGRES_URL is not None
    schema = f"pgmigrate_test_{uuid.uuid4().hex[:12]}"
    ensure_postgres_schema(POSTGRES_URL, schema, install_hint="pip install psycopg[binary]")
    scoped_dsn = dsn_with_search_path(POSTGRES_URL, schema)

    rc = main([str(source), scoped_dsn])
    assert rc == 0

    engine = create_engine(build_pg_url(scoped_dsn))
    try:
        with engine.connect() as conn:
            users = conn.execute(select(UserRow.__table__)).mappings().all()
            clock = conn.execute(select(RunChangeClockRow.__table__)).mappings().all()
            next_id = conn.execute(text("SELECT nextval(pg_get_serial_sequence('run_change_clock', 'id'))")).scalar_one()
    finally:
        engine.dispose()
    assert [u["email"] for u in users] == ["a@example.com"]
    assert clock[0]["value"] == 5
    assert next_id == 2  # sequence advanced past the copied id=1
