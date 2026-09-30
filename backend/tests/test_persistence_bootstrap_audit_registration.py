"""A fresh process must bootstrap the audit table before stamping head."""

import json
import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]

_FRESH_BOOTSTRAP = """
import asyncio, json, sqlite3, sys
from pathlib import Path
from deerflow.persistence.bootstrap import _get_head_revision
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine

async def main():
    database = Path(sys.argv[1])
    await init_engine(backend="sqlite", url=f"sqlite+aiosqlite:///{database}", sqlite_dir=str(database.parent))
    try:
        with sqlite3.connect(database) as connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            assert "audit_events" in tables, "fresh bootstrap stamped head without audit_events"
            indexes = {row[1] for row in connection.execute("PRAGMA index_list(audit_events)") if not row[1].startswith("sqlite_autoindex_")}
            assert indexes == {"ix_audit_events_occurred_at", "ix_audit_events_action", "ix_audit_events_organization_id", "ix_audit_events_actor_user_id"}
            revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            assert revision == _get_head_revision()
        # Import only after bootstrap: importing this first would mask a missing
        # registration through process-global Base.metadata side effects.
        from deerflow.persistence.audit_events import AuditEventRepository
        await AuditEventRepository(get_session_factory()).record(action="auth.login.failed", outcome="denied", details={"reason": "offline_fixture"})
        with sqlite3.connect(database) as connection:
            assert connection.execute("SELECT COUNT(*) FROM audit_events WHERE action='auth.login.failed' AND outcome='denied'").fetchone()[0] == 1
        print(json.dumps({"audit_table": True, "audit_indexes": sorted(indexes), "revision": revision, "native_failed_login_event_recorded": True}))
    finally:
        await close_engine()

asyncio.run(main())
"""


def test_fresh_process_bootstrap_registers_audit_table_and_native_logging(tmp_path):
    # An isolated interpreter avoids another test's AuditEventRow import
    # populating global metadata before the production registration entry point.
    completed = subprocess.run(
        [sys.executable, "-c", _FRESH_BOOTSTRAP, str(tmp_path / "fresh.db")],
        cwd=tmp_path,
        env={"PATH": os.defpath, "PYTHONPATH": os.pathsep.join(str(path) for path in [BACKEND, BACKEND / "packages/harness", BACKEND / "packages/extension-api"])},
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout.splitlines()[-1])
    assert result["audit_table"] and result["native_failed_login_event_recorded"]
    assert len(result["audit_indexes"]) == 4
