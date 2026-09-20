import sqlite3

import pytest

from scripts.momentum_migration_pilot import PilotInterrupted, rollback_migration, run_migration


def test_migration_resumes_reconciles_reruns_and_rolls_back(tmp_path):
    source = tmp_path / "source.db"
    target = tmp_path / "target.db"
    rows = [
        ("c-001", "Acme", "enterprise", 125_00, "2026-09-19T12:00:00Z"),
        ("c-002", "Beta", "growth", 75_00, "2026-09-19T12:01:00Z"),
        ("c-003", "Cedar", "growth", 50_00, "2026-09-19T12:02:00Z"),
    ]
    with sqlite3.connect(source) as db:
        db.execute(
            """CREATE TABLE customers (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, segment TEXT NOT NULL,
                revenue_cents INTEGER NOT NULL, updated_at TEXT NOT NULL
            )"""
        )
        db.executemany("INSERT INTO customers VALUES (?, ?, ?, ?, ?)", rows)
    with sqlite3.connect(target) as db:
        db.execute(
            """CREATE TABLE momentum_accounts (
                id TEXT PRIMARY KEY, display_name TEXT NOT NULL, segment TEXT NOT NULL,
                revenue_cents INTEGER NOT NULL, source_updated_at TEXT NOT NULL,
                migration_source TEXT
            )"""
        )
        db.execute("INSERT INTO momentum_accounts VALUES ('legacy', 'Legacy', 'legacy', 1, 'old', NULL)")

    with pytest.raises(PilotInterrupted):
        run_migration(source, target, fail_after=2)
    receipt = run_migration(source, target)
    assert receipt.source_count == receipt.target_count == 3
    assert receipt.revenue_cents == 250_00
    assert receipt.segment_revenue_cents == {"enterprise": 125_00, "growth": 125_00}
    assert run_migration(source, target) == receipt
    assert rollback_migration(target) == 1

    with sqlite3.connect(target) as db:
        assert db.execute("SELECT id, display_name FROM momentum_accounts").fetchall() == [("legacy", "Legacy")]
        assert db.execute("SELECT COUNT(*) FROM momentum_migration_state").fetchone()[0] == 0
