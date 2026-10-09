"""Compare a SQLite DeerFlow database against its PostgreSQL cutover target.

Checks, matching the M7 rehearsal criteria (plans/momentum-backend-goal.md):
  - row count per table (every table ``migrate_sqlite_to_postgres.py`` owns)
  - alembic head revision: both databases must be stamped at the same
    revision, and it must be this checkout's current head
  - SHA-256 rollup of ``project_documents.sha256`` (the M7 "document
    hashes" check -- each row already carries its body's hash; this compares
    the row-for-row set of hashes, not file bytes on disk)

Prints a PASS/FAIL receipt and exits non-zero on any mismatch. Never prints
the DSN or any credential.

Usage (run from backend/):
    PYTHONPATH=. uv run python scripts/verify_cutover.py \\
        /path/to/deerflow.db postgresql://user:pass@host:5432/deerflow
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, func, select, text
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.engine import Engine, make_url

import deerflow.persistence.models  # noqa: F401 -- registers ORM tables on Base.metadata
from deerflow.persistence.base import Base

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "packages" / "harness" / "deerflow" / "persistence" / "migrations"


def local_head() -> str:
    """This checkout's current alembic head, read off the versions/ tree on disk."""
    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    head = ScriptDirectory.from_config(cfg).get_current_head()
    if head is None:
        raise RuntimeError("alembic has no head revision -- versions/ directory is empty")
    return head


def db_alembic_version(engine: Engine) -> str | None:
    """The single ``alembic_version`` row, or None if the table doesn't exist."""
    if not sa_inspect(engine).has_table("alembic_version"):
        return None
    with engine.connect() as conn:
        return conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()


def table_counts(engine: Engine) -> dict[str, int]:
    counts: dict[str, int] = {}
    with engine.connect() as conn:
        for table in Base.metadata.sorted_tables:
            counts[table.name] = conn.execute(select(func.count()).select_from(table)).scalar_one()
    return counts


def document_hash_receipt(engine: Engine) -> tuple[int, str]:
    """(row count, SHA-256 digest of the sorted ``project_documents.sha256`` values).

    A rollup over already-stored per-document hashes, not a re-hash of file
    bytes on disk: ``ProjectDocumentRow.sha256`` is computed once at upload
    time and is exactly what M7 calls the "document hashes" check.
    """
    table = Base.metadata.tables["project_documents"]
    with engine.connect() as conn:
        hashes = sorted(conn.execute(select(table.c.sha256)).scalars())
    digest = hashlib.sha256("\n".join(hashes).encode()).hexdigest()
    return len(hashes), digest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("sqlite_path", help="Path to the source deerflow.db SQLite file")
    parser.add_argument("postgres_dsn", help="Target PostgreSQL DSN, e.g. postgresql://user:pass@host:5432/deerflow")
    args = parser.parse_args(argv)

    sqlite_path = Path(args.sqlite_path)
    if not sqlite_path.is_file():
        parser.error(f"sqlite file not found: {sqlite_path}")

    pg_url = make_url(args.postgres_dsn)
    if pg_url.drivername in ("postgresql", "postgres"):
        pg_url = pg_url.set(drivername="postgresql+psycopg")

    source = create_engine(f"sqlite:///{sqlite_path}")
    target = create_engine(pg_url)
    ok = True
    try:
        head = local_head()
        source_rev = db_alembic_version(source)
        target_rev = db_alembic_version(target)
        rev_ok = source_rev == head and target_rev == head
        ok = ok and rev_ok
        print(f"alembic head (this checkout): {head}")
        print(f"alembic head (source):        {source_rev}  {'OK' if source_rev == head else 'MISMATCH'}")
        print(f"alembic head (target):        {target_rev}  {'OK' if target_rev == head else 'MISMATCH'}")
        print()

        source_counts = table_counts(source)
        target_counts = table_counts(target)
        name_width = max((len(n) for n in source_counts), default=5)
        print(f"{'table':<{name_width}}  {'source':>8}  {'target':>8}  status")
        for name in source_counts:
            s, t = source_counts[name], target_counts.get(name, 0)
            row_ok = s == t
            ok = ok and row_ok
            print(f"{name:<{name_width}}  {s:>8}  {t:>8}  {'OK' if row_ok else 'MISMATCH'}")
        print()

        source_doc_count, source_doc_digest = document_hash_receipt(source)
        target_doc_count, target_doc_digest = document_hash_receipt(target)
        doc_ok = source_doc_count == target_doc_count and source_doc_digest == target_doc_digest
        ok = ok and doc_ok
        print(f"project_documents: {source_doc_count} source / {target_doc_count} target rows")
        print(f"document hash digest (source): {source_doc_digest}")
        print(f"document hash digest (target): {target_doc_digest}  {'OK' if doc_ok else 'MISMATCH'}")
        print()
    finally:
        source.dispose()
        target.dispose()

    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
