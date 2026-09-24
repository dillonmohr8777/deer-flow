"""Tests for scripts/verify_cutover.py.

Offline tests compare two SQLite databases (standing in for source and
Postgres target -- every check here is dialect-agnostic Core SQL). The one
live test runs the real migrator against Postgres first, then verifies it,
gated by ``TEST_POSTGRES_URI`` like the rest of this repo's live-Postgres
tests.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from deerflow.persistence.projects.model import ProjectDocumentRow, ProjectRow
from deerflow.persistence.user.model import UserRow
from scripts.migrate_sqlite_to_postgres import run_alembic_upgrade
from scripts.verify_cutover import db_alembic_version, document_hash_receipt, local_head, main, table_counts

POSTGRES_URL = os.environ.get("TEST_POSTGRES_URI")


def _make_db_at_head(path: Path) -> None:
    run_alembic_upgrade(make_url(f"sqlite:///{path}"))


def _seed(path: Path, *, email: str, doc_sha: str) -> None:
    _make_db_at_head(path)
    engine = create_engine(f"sqlite:///{path}")
    try:
        with engine.begin() as conn:
            conn.execute(UserRow.__table__.insert(), {"id": "u1", "email": email})
            conn.execute(ProjectRow.__table__.insert(), {"id": "p1", "user_id": "u1", "name": "Proj"})
            conn.execute(
                ProjectDocumentRow.__table__.insert(),
                {
                    "id": "d1",
                    "project_id": "p1",
                    "user_id": "u1",
                    "name": "doc.txt",
                    "stored_relpath": "u1/p1/d1",
                    "sha256": doc_sha,
                    "size_bytes": 3,
                },
            )
    finally:
        engine.dispose()


def test_local_head_is_current_pinned_revision():
    # Pinned per plans/momentum-backend-goal.md M7; bump this alongside a
    # new head revision so the drift is deliberate, not silent.
    assert local_head() == "0035_fleet_agent_bindings"


def test_db_alembic_version_none_when_table_missing(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    try:
        assert db_alembic_version(engine) is None
    finally:
        engine.dispose()


def test_db_alembic_version_matches_head_after_upgrade(tmp_path):
    path = tmp_path / "db.db"
    _make_db_at_head(path)
    engine = create_engine(f"sqlite:///{path}")
    try:
        assert db_alembic_version(engine) == local_head()
    finally:
        engine.dispose()


def test_table_counts_reflects_seeded_rows(tmp_path):
    path = tmp_path / "db.db"
    _seed(path, email="a@example.com", doc_sha="ab" * 32)
    engine = create_engine(f"sqlite:///{path}")
    try:
        counts = table_counts(engine)
    finally:
        engine.dispose()
    assert counts["users"] == 1
    assert counts["project_documents"] == 1


def test_document_hash_receipt_matches_for_identical_data(tmp_path):
    source, target = tmp_path / "source.db", tmp_path / "target.db"
    _seed(source, email="a@example.com", doc_sha="ab" * 32)
    _seed(target, email="a@example.com", doc_sha="ab" * 32)
    src_engine, tgt_engine = create_engine(f"sqlite:///{source}"), create_engine(f"sqlite:///{target}")
    try:
        assert document_hash_receipt(src_engine) == document_hash_receipt(tgt_engine)
    finally:
        src_engine.dispose()
        tgt_engine.dispose()


def test_document_hash_receipt_differs_for_different_hashes(tmp_path):
    source, target = tmp_path / "source.db", tmp_path / "target.db"
    _seed(source, email="a@example.com", doc_sha="ab" * 32)
    _seed(target, email="a@example.com", doc_sha="cd" * 32)
    src_engine, tgt_engine = create_engine(f"sqlite:///{source}"), create_engine(f"sqlite:///{target}")
    try:
        assert document_hash_receipt(src_engine) != document_hash_receipt(tgt_engine)
    finally:
        src_engine.dispose()
        tgt_engine.dispose()


def test_main_passes_for_identical_databases(tmp_path):
    source, target = tmp_path / "source.db", tmp_path / "target.db"
    _seed(source, email="a@example.com", doc_sha="ab" * 32)
    _seed(target, email="a@example.com", doc_sha="ab" * 32)
    assert main([str(source), f"sqlite:///{target}"]) == 0


def test_main_fails_for_divergent_databases(tmp_path):
    source, target = tmp_path / "source.db", tmp_path / "target.db"
    _seed(source, email="a@example.com", doc_sha="ab" * 32)
    _seed(target, email="different@example.com", doc_sha="cd" * 32)
    assert main([str(source), f"sqlite:///{target}"]) == 1


@pytest.mark.skipif(not POSTGRES_URL, reason="set TEST_POSTGRES_URI to run the live PostgreSQL verify test")
def test_verify_against_real_postgres_after_migration(tmp_path):
    from deerflow.persistence.postgres_schema import dsn_with_search_path, ensure_postgres_schema
    from scripts.migrate_sqlite_to_postgres import main as migrate_main

    source = tmp_path / "source.db"
    _seed(source, email="a@example.com", doc_sha="ab" * 32)

    assert POSTGRES_URL is not None
    schema = f"pgverify_test_{uuid.uuid4().hex[:12]}"
    ensure_postgres_schema(POSTGRES_URL, schema, install_hint="pip install psycopg[binary]")
    scoped_dsn = dsn_with_search_path(POSTGRES_URL, schema)

    assert migrate_main([str(source), scoped_dsn]) == 0
    assert main([str(source), scoped_dsn]) == 0
