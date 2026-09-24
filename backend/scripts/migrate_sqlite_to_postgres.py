"""Copy a SQLite DeerFlow database into an empty PostgreSQL database.

1. Runs ``alembic upgrade head`` against the target (creates every table
   Alembic owns -- see ``persistence/migrations/env.py``).
2. Copies every one of those tables, in foreign-key order
   (``Base.metadata.sorted_tables``), in batches, preserving primary keys,
   JSON, and timestamps.
3. Resets each integer-PK sequence to MAX(id)+1 so the next app-issued
   insert does not collide with a copied row.

LangGraph's checkpoint tables (``checkpoints``, ``checkpoint_blobs``,
``checkpoint_writes``, ``checkpoint_migrations``) are NOT copied -- they are
not owned by Alembic/``Base.metadata`` and have their own lifecycle (see
``persistence/migrations/env.py``). A cutover that must keep live
conversation history needs a separate step for those; this script only
moves DeerFlow's own application tables.

Usage (run from backend/):
    PYTHONPATH=. uv run python scripts/migrate_sqlite_to_postgres.py \\
        /path/to/deerflow.db postgresql://user:pass@host:5432/deerflow

Refuses a target that already has any tables, unless ``--force`` -- which
also clears (DELETE, reverse FK order) every table this script owns before
re-copying, so re-running after a partial failure is safe.

Exits non-zero if any table's post-copy row count does not match the
source. Never prints the DSN or any credential.
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from sqlalchemy import BigInteger, Integer, create_engine, func, select, text
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.engine import URL, Engine, make_url

import deerflow.persistence.models  # noqa: F401 -- registers ORM tables on Base.metadata
from deerflow.persistence.base import Base
from deerflow.persistence.bootstrap import _escape_url_for_alembic

logger = logging.getLogger("migrate_sqlite_to_postgres")

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "packages" / "harness" / "deerflow" / "persistence" / "migrations"

DEFAULT_BATCH_SIZE = 500


@dataclass
class TableReport:
    name: str
    source_count: int
    target_count: int

    @property
    def ok(self) -> bool:
        return self.source_count == self.target_count


def build_pg_url(dsn: str) -> URL:
    """Normalize *dsn* to the sync psycopg driver DeerFlow already ships with."""
    url = make_url(dsn)
    if url.drivername in ("postgresql", "postgres"):
        url = url.set(drivername="postgresql+psycopg")
    return url


def is_target_empty(engine: Engine) -> bool:
    return len(sa_inspect(engine).get_table_names()) == 0


def run_alembic_upgrade(pg_url: URL) -> None:
    """Run alembic upgrade head against *pg_url*.

    Named for the production Postgres path, but works against any backend
    alembic supports: ``migrations/env.py`` always builds an async engine
    (``create_async_engine``), so a plain sync ``sqlite://`` URL -- as used by
    this module's own offline tests -- is normalized to the async
    ``sqlite+aiosqlite`` driver first, matching how the app builds its own
    sqlite URLs (``DatabaseConfig.app_sqlalchemy_url``). Does not mutate the
    caller's ``pg_url``: the production Postgres path is unaffected.
    """
    url = pg_url
    if url.get_backend_name() == "sqlite" and "aiosqlite" not in (url.drivername or ""):
        url = url.set(drivername="sqlite+aiosqlite")
    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", _escape_url_for_alembic(url.render_as_string(hide_password=False)))
    logger.info("running alembic upgrade head against target")
    alembic_command.upgrade(cfg, "head")


def clear_tables(engine: Engine) -> None:
    """Delete every row from every DeerFlow-owned table, children first.

    Safe no-op on a freshly-created (empty) schema; makes a ``--force`` run
    against a previously-populated target idempotent instead of colliding on
    primary keys.
    """
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())


def copy_all_tables(source: Engine, target: Engine, *, batch_size: int = DEFAULT_BATCH_SIZE) -> list[TableReport]:
    """Copy every ``Base.metadata`` table from *source* to *target*, in FK order.

    Works against any two SQLAlchemy engines (not just SQLite -> PostgreSQL):
    the copy is plain Core ``select``/``insert`` against the shared ``Table``
    objects, so column types (JSON, DateTime, ...) round-trip through their
    normal Python values on both ends.
    """
    reports: list[TableReport] = []
    with source.connect() as src_conn:
        for table in Base.metadata.sorted_tables:
            source_count = src_conn.execute(select(func.count()).select_from(table)).scalar_one()
            copied = 0
            with target.begin() as dst_conn:
                rows = src_conn.execute(select(table)).mappings()
                for batch in rows.partitions(batch_size):
                    values = [dict(row) for row in batch]
                    if values:
                        dst_conn.execute(table.insert(), values)
                        copied += len(values)
            target_count = copied
            reports.append(TableReport(table.name, source_count, target_count))
            logger.info("copied %s: %d/%d rows", table.name, target_count, source_count)
    return reports


def reset_sequences(engine: Engine) -> None:
    """Advance every integer-PK column's PostgreSQL sequence past its copied max.

    No-op for non-PostgreSQL engines and for PK columns with no backing
    sequence (string/UUID primary keys, which DeerFlow uses for most tables).
    """
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            for column in table.primary_key.columns:
                if not isinstance(column.type, (Integer, BigInteger)):
                    continue
                seq = conn.execute(text("SELECT pg_get_serial_sequence(:t, :c)"), {"t": table.name, "c": column.name}).scalar_one_or_none()
                if not seq:
                    continue
                conn.execute(
                    text(f'SELECT setval(:seq, COALESCE((SELECT MAX("{column.name}") FROM "{table.name}"), 1), (SELECT MAX("{column.name}") FROM "{table.name}") IS NOT NULL)'),  # noqa: S608 -- table/column names are trusted ORM metadata, not user input
                    {"seq": seq},
                )
                logger.info("reset sequence for %s.%s", table.name, column.name)


def _print_report(reports: list[TableReport]) -> bool:
    """Print the per-table row-count report; return True iff every table matched."""
    name_width = max((len(r.name) for r in reports), default=5)
    print(f"{'table':<{name_width}}  {'source':>8}  {'target':>8}  status")
    all_ok = True
    for r in reports:
        status = "OK" if r.ok else "MISMATCH"
        all_ok = all_ok and r.ok
        print(f"{r.name:<{name_width}}  {r.source_count:>8}  {r.target_count:>8}  {status}")
    total_source = sum(r.source_count for r in reports)
    total_target = sum(r.target_count for r in reports)
    print(f"{'TOTAL':<{name_width}}  {total_source:>8}  {total_target:>8}  {'OK' if all_ok else 'MISMATCH'}")
    return all_ok


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("sqlite_path", help="Path to the source deerflow.db SQLite file")
    parser.add_argument("postgres_dsn", help="Target PostgreSQL DSN, e.g. postgresql://user:pass@host:5432/deerflow")
    parser.add_argument("--force", action="store_true", help="Allow a non-empty target; clears every DeerFlow table before copying")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help=f"Rows per insert batch (default {DEFAULT_BATCH_SIZE})")
    args = parser.parse_args(argv)

    sqlite_path = Path(args.sqlite_path)
    if not sqlite_path.is_file():
        parser.error(f"sqlite file not found: {sqlite_path}")

    pg_url = build_pg_url(args.postgres_dsn)
    safe_target = pg_url.render_as_string(hide_password=True)

    source = create_engine(f"sqlite:///{sqlite_path}")
    target = create_engine(pg_url)
    try:
        if not is_target_empty(target) and not args.force:
            logger.error("target %s already has tables; pass --force to clear and re-copy", safe_target)
            return 2

        run_alembic_upgrade(pg_url)
        clear_tables(target)
        reports = copy_all_tables(source, target, batch_size=args.batch_size)
        reset_sequences(target)
    finally:
        source.dispose()
        target.dispose()

    ok = _print_report(reports)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
