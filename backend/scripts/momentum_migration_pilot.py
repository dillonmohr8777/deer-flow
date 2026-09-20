"""Disposable, deterministic database-migration pilot for Momentum acceptance."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

PIPELINE = "momentum-customers-v1"


class PilotInterrupted(RuntimeError):
    """Raised only by the synthetic failure hook used to prove resume behavior."""


@dataclass(frozen=True)
class MigrationReceipt:
    pipeline: str
    status: str
    source_count: int
    target_count: int
    revenue_cents: int
    segment_revenue_cents: dict[str, int]
    digest: str

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _rows(connection: sqlite3.Connection) -> list[tuple[str, str, str, int, str]]:
    columns = {row[1] for row in connection.execute("PRAGMA table_info(customers)")}
    required = {"id", "name", "segment", "revenue_cents", "updated_at"}
    if not required <= columns:
        raise ValueError(f"source customers table is missing: {sorted(required - columns)}")
    return connection.execute(
        "SELECT id, name, segment, revenue_cents, updated_at FROM customers ORDER BY id"
    ).fetchall()


def _digest(rows: list[tuple[str, str, str, int, str]]) -> str:
    payload = json.dumps(rows, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(payload).hexdigest()


def _prepare_target(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS momentum_accounts (
            id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            segment TEXT NOT NULL,
            revenue_cents INTEGER NOT NULL CHECK (revenue_cents >= 0),
            source_updated_at TEXT NOT NULL,
            migration_source TEXT
        );
        CREATE TABLE IF NOT EXISTS momentum_accounts_before_pilot AS
            SELECT * FROM momentum_accounts WHERE 0;
        CREATE TABLE IF NOT EXISTS momentum_migration_state (
            pipeline TEXT PRIMARY KEY,
            source_digest TEXT NOT NULL,
            last_source_id TEXT,
            status TEXT NOT NULL,
            applied_count INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )


def _receipt(connection: sqlite3.Connection, source_rows: list[tuple[str, str, str, int, str]]) -> MigrationReceipt:
    target_rows = connection.execute(
        """SELECT id, display_name, segment, revenue_cents, source_updated_at
           FROM momentum_accounts WHERE migration_source = ? ORDER BY id""",
        (PIPELINE,),
    ).fetchall()
    source_digest = _digest(source_rows)
    target_digest = _digest(target_rows)
    if source_digest != target_digest:
        raise ValueError("source/target reconciliation digest mismatch")
    segments = {
        segment: total
        for segment, total in connection.execute(
            """SELECT segment, SUM(revenue_cents) FROM momentum_accounts
               WHERE migration_source = ? GROUP BY segment ORDER BY segment""",
            (PIPELINE,),
        )
    }
    return MigrationReceipt(
        pipeline=PIPELINE,
        status="complete",
        source_count=len(source_rows),
        target_count=len(target_rows),
        revenue_cents=sum(row[3] for row in target_rows),
        segment_revenue_cents=segments,
        digest=source_digest,
    )


def run_migration(source: str | Path, target: str | Path, *, fail_after: int | None = None) -> MigrationReceipt:
    """Migrate the fixed synthetic contract; reruns resume or return the same receipt."""
    source_path = Path(source).resolve()
    target_path = Path(target).resolve()
    if source_path == target_path:
        raise ValueError("source and target must be different databases")
    if fail_after is not None and fail_after < 1:
        raise ValueError("fail_after must be positive")

    with sqlite3.connect(f"file:{source_path.as_posix()}?mode=ro", uri=True) as source_db:
        source_rows = _rows(source_db)
    source_digest = _digest(source_rows)

    with sqlite3.connect(target_path) as target_db:
        _prepare_target(target_db)
        state = target_db.execute(
            "SELECT source_digest, last_source_id, status FROM momentum_migration_state WHERE pipeline = ?",
            (PIPELINE,),
        ).fetchone()
        if state is None:
            target_db.execute("DELETE FROM momentum_accounts_before_pilot")
            target_db.execute("INSERT INTO momentum_accounts_before_pilot SELECT * FROM momentum_accounts")
            target_db.execute(
                "INSERT INTO momentum_migration_state VALUES (?, ?, NULL, 'running', 0, ?)",
                (PIPELINE, source_digest, _now()),
            )
            target_db.commit()
            last_source_id = None
        else:
            recorded_digest, last_source_id, status = state
            if recorded_digest != source_digest:
                raise ValueError("source changed after migration started")
            if status == "complete":
                return _receipt(target_db, source_rows)

        applied = 0
        for row in source_rows:
            if last_source_id is not None and row[0] <= last_source_id:
                continue
            target_db.execute(
                """INSERT INTO momentum_accounts
                       (id, display_name, segment, revenue_cents, source_updated_at, migration_source)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                       display_name = excluded.display_name,
                       segment = excluded.segment,
                       revenue_cents = excluded.revenue_cents,
                       source_updated_at = excluded.source_updated_at,
                       migration_source = excluded.migration_source""",
                (*row, PIPELINE),
            )
            target_db.execute(
                """UPDATE momentum_migration_state
                   SET last_source_id = ?, applied_count = applied_count + 1, updated_at = ?
                   WHERE pipeline = ?""",
                (row[0], _now(), PIPELINE),
            )
            target_db.commit()
            applied += 1
            if fail_after is not None and applied == fail_after:
                raise PilotInterrupted(f"synthetic interruption after {applied} rows")

        receipt = _receipt(target_db, source_rows)
        target_db.execute(
            "UPDATE momentum_migration_state SET status = 'complete', updated_at = ? WHERE pipeline = ?",
            (_now(), PIPELINE),
        )
        target_db.commit()
        return receipt


def rollback_migration(target: str | Path) -> int:
    """Restore the exact pre-pilot account rows and remove the pilot checkpoint."""
    with sqlite3.connect(Path(target).resolve()) as target_db:
        _prepare_target(target_db)
        if target_db.execute(
            "SELECT 1 FROM momentum_migration_state WHERE pipeline = ?", (PIPELINE,)
        ).fetchone() is None:
            raise ValueError("no migration state to roll back")
        target_db.execute("DELETE FROM momentum_accounts")
        target_db.execute("INSERT INTO momentum_accounts SELECT * FROM momentum_accounts_before_pilot")
        restored = target_db.execute("SELECT COUNT(*) FROM momentum_accounts").fetchone()[0]
        target_db.execute("DELETE FROM momentum_migration_state WHERE pipeline = ?", (PIPELINE,))
        target_db.execute("DELETE FROM momentum_accounts_before_pilot")
        target_db.commit()
        return restored
