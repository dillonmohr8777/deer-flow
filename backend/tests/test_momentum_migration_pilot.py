import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.momentum_migration_pilot import PilotInterrupted, assess_source, rollback_migration, run_migration


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


@pytest.fixture
def databases(tmp_path):
    source, target = tmp_path / "source.db", tmp_path / "target.db"
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE customers(id TEXT, name TEXT, segment TEXT, revenue_cents INTEGER, updated_at TEXT)")
        db.executemany("INSERT INTO customers VALUES (?, ?, ?, ?, ?)", [("a", "Synthetic A", "one", 100, "now"), ("b", "Synthetic B", "two", 200, "now")])
    with sqlite3.connect(target) as db:
        db.execute("CREATE TABLE momentum_accounts(id TEXT PRIMARY KEY, display_name TEXT, segment TEXT, revenue_cents INTEGER, source_updated_at TEXT, migration_source TEXT)")
        db.executemany("INSERT INTO momentum_accounts VALUES (?, ?, ?, ?, ?, ?)", [("b", "Original B", "old", 7, "old", None), ("legacy", "Original", "old", 1, "old", None)])
    return source, target


def accounts(target):
    with sqlite3.connect(target) as db:
        return db.execute("SELECT * FROM momentum_accounts ORDER BY id").fetchall()


def test_selective_recovery_preserves_target_only_insert_and_update(databases):
    source, target = databases
    run_migration(source, target)
    with sqlite3.connect(target) as db:
        db.execute("UPDATE momentum_accounts SET display_name='Updated after cutover' WHERE id='legacy'")
        db.execute("INSERT INTO momentum_accounts VALUES ('new', 'New after cutover', 'new', 900, 'later', NULL)")
    assert rollback_migration(target) == 3
    assert accounts(target) == [("b", "Original B", "old", 7, "old", None), ("legacy", "Updated after cutover", "old", 1, "old", None), ("new", "New after cutover", "new", 900, "later", None)]


def test_changed_migrated_row_holds_resume_and_rollback_without_data_loss(databases):
    source, target = databases
    run_migration(source, target)
    with sqlite3.connect(target) as db:
        db.execute("UPDATE momentum_accounts SET revenue_cents=777 WHERE id='a'")
    saved = accounts(target)
    for operation in (lambda: rollback_migration(target), lambda: run_migration(source, target)):
        with pytest.raises(ValueError, match="reconcile forward"):
            operation()
        assert accounts(target) == saved
    with sqlite3.connect(target) as db:
        assert db.execute("SELECT status FROM momentum_migration_state").fetchone() == ("complete",)


def test_pending_target_write_is_not_overwritten_after_interruption(databases):
    source, target = databases
    with pytest.raises(PilotInterrupted):
        run_migration(source, target, fail_after=1)
    with sqlite3.connect(target) as db:
        db.execute("UPDATE momentum_accounts SET display_name='Concurrent B' WHERE id='b'")
    saved = accounts(target)
    with pytest.raises(ValueError, match="pending target row changed"):
        run_migration(source, target)
    assert accounts(target) == saved
    assert rollback_migration(target) == 2
    assert accounts(target)[0][1] == "Concurrent B"


def test_legacy_or_missing_write_evidence_never_allows_destructive_recovery(databases):
    source, target = databases
    run_migration(source, target)
    with sqlite3.connect(target) as db:
        db.execute("DELETE FROM momentum_accounts_pilot_applied")
    saved = accounts(target)
    with pytest.raises(ValueError, match="write evidence is missing"):
        rollback_migration(target)
    assert accounts(target) == saved


def test_assessment_reconciles_rejects_and_keeps_source_read_only(databases):
    source, target = databases
    with sqlite3.connect(source) as db:
        db.executemany("INSERT INTO customers VALUES (?, ?, ?, ?, ?)", [("duplicate", "Do not export", "one", 1, "now"), ("duplicate", "Do not export", "one", 1, "now"), ("bad", "Do not export", "one", -1, "now")])
    before = source.read_bytes()
    result = assess_source(source)
    assert result["source_count"] == result["accepted_count"] + result["rejected_count"] == 5
    assert (result["accepted_count"], result["rejected_count"]) == (2, 3)
    assert "Do not export" not in str(result)
    assert source.read_bytes() == before
    saved = target.read_bytes()
    with pytest.raises(ValueError, match="source has rejected rows"):
        run_migration(source, target)
    assert target.read_bytes() == saved


def test_fresh_process_resumes_existing_checkpoint(databases):
    source, target = databases
    backend = Path(__file__).resolve().parents[1]
    code = "from scripts.momentum_migration_pilot import run_migration; import sys; run_migration(sys.argv[1], sys.argv[2], fail_after=1)"
    first = subprocess.run([sys.executable, "-B", "-c", code, str(source), str(target)], cwd=backend, capture_output=True, text=True, check=False)
    assert first.returncode != 0 and "PilotInterrupted" in first.stderr
    code = "from scripts.momentum_migration_pilot import run_migration; import sys; print(run_migration(sys.argv[1], sys.argv[2]).to_json())"
    second = subprocess.run([sys.executable, "-B", "-c", code, str(source), str(target)], cwd=backend, capture_output=True, text=True, check=False)
    assert second.returncode == 0 and '"target_count": 2' in second.stdout
    assert len(accounts(target)) == 3
