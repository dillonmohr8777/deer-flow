"""Explicit physical-old-source rollback proof; invoke with --old-root and --output.

The child imports only the actual accepted checkout. It runs old bootstrap and
repositories against new persisted rows, including old writes and inserts.
This is deliberately separate from pytest's shared module/mocking cache.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace


async def old_child(root: Path, database: Path, expected: Path, action: str) -> dict:
    from sqlalchemy import text

    import deerflow.persistence.bootstrap as bootstrap
    import deerflow.persistence.engine as engine_module
    import deerflow.persistence.run.model as model
    import deerflow.persistence.run.sql as sql

    sources = {}
    for module in (bootstrap, engine_module, model, sql):
        location = Path(module.__file__).resolve()
        assert location.is_relative_to(root / "backend" / "packages" / "harness"), location
        sources[module.__name__] = str(location)
    assert "run_limits_json" not in model.RunRow.__table__.columns
    await engine_module.init_engine("sqlite", url=f"sqlite+aiosqlite:///{database.as_posix()}", sqlite_dir=str(database.parent))
    repository = sql.RunRepository(engine_module.get_session_factory())
    try:
        async with engine_module.get_engine().connect() as connection:
            revision = (await connection.execute(text("SELECT version_num FROM alembic_version"))).scalar_one()
            assert revision == "0052_board_portal"
        if action == "seed":
            await repository.put("old-before", thread_id="old-before", status="success", kwargs={"written_by": "old-before"}, user_id=None)
            return {"sources": sources, "revision": revision, "seeded": "old-before"}
        rows = json.loads(expected.read_text())
        for expected_row in rows:
            row = await repository.get(expected_row["run_id"], user_id=None)
            assert row["kwargs"] == expected_row["kwargs"]
            assert row["status"] == expected_row["status"]
            assert "run_limits" not in row and "run_limits_json" not in row
            async with engine_module.get_engine().connect() as connection:
                before = (await connection.execute(text("SELECT run_limits_json FROM runs WHERE run_id=:run_id"), {"run_id": row["run_id"]})).scalar_one()
            assert json.loads(before) == expected_row["run_limits"]
            # Exercise the actual old snapshot writer, including metadata and
            # kwargs containing caller-spoofed policy names. It cannot map the
            # additive private column, so it must preserve the captured value.
            await repository.put(
                row["run_id"],
                thread_id=row["thread_id"],
                status=row["status"],
                kwargs=row["kwargs"],
                metadata={"run_limits": None, "run_limits_json": {"execution_timeout_seconds": None}, "old_writer": True},
                error=row.get("error"),
                stop_reason=row.get("stop_reason"),
                user_id=row.get("user_id"),
                owner_worker_id=row.get("owner_worker_id"),
                lease_expires_at=row.get("lease_expires_at"),
            )
            async with engine_module.get_engine().connect() as connection:
                after = (await connection.execute(text("SELECT run_limits_json FROM runs WHERE run_id=:run_id"), {"run_id": row["run_id"]})).scalar_one()
            assert after == before
            assert (await repository.get(row["run_id"], user_id=None))["kwargs"] == expected_row["kwargs"]
        if action == "final":
            await repository.put("old-after", thread_id="old-after", status="success", kwargs={"written_by": "old-after"}, user_id=None)
        return {"sources": sources, "revision": revision, "checked": len(rows), "action": action}
    finally:
        await engine_module.close_engine()


async def prove(old_root: Path, output: Path) -> dict:
    from deerflow.config.run_config import RunConfig
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
    from deerflow.persistence.run.sql import RunRepository
    from deerflow.runtime.runs.manager import RunManager, RunStartOutcome
    from deerflow.runtime.runs.schemas import RunStatus
    from deerflow.runtime.user_context import reset_current_user, set_current_user

    token = set_current_user(SimpleNamespace(id="synthetic-rollback-user"))
    output.mkdir(parents=True, exist_ok=False)
    database = output / "rollback.db"
    expected = output / "expected.json"
    reports = []
    managers = []

    async def child(action: str, rows: list[dict] | None = None) -> None:
        if rows is not None:
            expected.write_text(json.dumps(rows, indent=2))
        environment = dict(os.environ)
        environment["PYTHONPATH"] = os.pathsep.join(str(old_root / path) for path in ("backend/packages/harness", "backend/packages/extension-api", "backend"))
        process = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, str(Path(__file__).resolve()), "--old-child", "--old-root", str(old_root), "--output", str(database), "--expected", str(expected), "--action", action],
            cwd=old_root,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=45,
            check=False,
        )
        stdout = process.stdout
        log = stdout.decode("utf-8", errors="replace")
        (output / f"old-{action}.log").write_text(log)
        assert process.returncode == 0, log
        reports.append(json.loads(log.splitlines()[-1]))

    await child("seed")
    await init_engine("sqlite", url=f"sqlite+aiosqlite:///{database.as_posix()}", sqlite_dir=str(output))
    repository = RunRepository(get_session_factory())
    try:
        assert (await repository.get("old-before", user_id=None))["run_limits"] is None
        original_kwargs = {"config": {"context": {"execution_timeout_seconds": None}}, "run_limits_json": {"execution_deadline_at": "2099-01-01"}, "messages": [{"type": "human", "content": "synthetic"}]}
        manager = RunManager(store=repository, run_config=RunConfig(execution_timeout_seconds=0.05, prestart_wait_seconds=300))
        managers.append(manager)
        record = await manager.create_or_reject("new-finite", kwargs=original_kwargs)
        pending = await repository.get(record.run_id, user_id=None)
        await child("pending", [pending])
        assert (await repository.get(record.run_id, user_id=None))["run_limits"] == pending["run_limits"]
        assert await manager.try_start(record.run_id) == RunStartOutcome.started
        started = await repository.get(record.run_id, user_id=None)
        assert started["kwargs"] == original_kwargs and started["run_limits"]["started_at"] is not None
        await asyncio.wait_for(record.abort_event.wait(), 5)
        supervisor = manager._limit_tasks.get(record.run_id)
        if supervisor is not None:
            await asyncio.wait_for(supervisor, 5)
        timed_out = await repository.get(record.run_id, user_id=None)
        assert timed_out["status"] == "timeout" and timed_out["kwargs"] == original_kwargs
        assert timed_out["run_limits"] == started["run_limits"]
        terminal_rows = [timed_out]
        for value, name in ((None, "null"), (0, "zero")):
            disabled = RunManager(store=repository, run_config=RunConfig(execution_timeout_seconds=value, prestart_wait_seconds=value))
            managers.append(disabled)
            disabled_record = await disabled.create_or_reject(f"disabled-{name}", kwargs=original_kwargs)
            assert await disabled.try_start(disabled_record.run_id) == RunStartOutcome.started
            await disabled.set_status(disabled_record.run_id, RunStatus.success)
            row = await repository.get(disabled_record.run_id, user_id=None)
            assert row["run_limits"]["execution_deadline_at"] is None and row["kwargs"] == original_kwargs
            terminal_rows.append(row)
        await child("final", terminal_rows)
        for before in terminal_rows:
            after = await repository.get(before["run_id"], user_id=None)
            assert after["run_limits"] == before["run_limits"] and after["kwargs"] == original_kwargs
            assert after["metadata"]["old_writer"] is True
        old_after = await repository.get("old-after", user_id=None)
        assert old_after["kwargs"] == {"written_by": "old-after"} and old_after["run_limits"] is None
        return {
            "old_source_root": str(old_root),
            "new_sql_source": __import__("deerflow.persistence.run.sql", fromlist=["x"]).__file__,
            "reports": reports,
            "timeout_status": timed_out["status"],
            "private_captures_preserved": True,
            "kwargs_exact": True,
            "old_inserts_readable": True,
        }
    finally:
        for manager in managers:
            for run_id in list(manager._limit_tasks):
                await manager.stop_run_limit(run_id)
        await close_engine()
        reset_current_user(token)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected", type=Path)
    parser.add_argument("--action", default="seed")
    parser.add_argument("--old-child", action="store_true")
    arguments = parser.parse_args()
    result = asyncio.run(old_child(arguments.old_root.resolve(), arguments.output, arguments.expected, arguments.action) if arguments.old_child else prove(arguments.old_root.resolve(), arguments.output))
    print(json.dumps(result, default=str))
