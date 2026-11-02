"""Server-owned run-provenance receipts (synthetic identifiers only)."""

from __future__ import annotations

import asyncio
import json
import os
import re
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.gateway import run_provenance as rp

SERVICES = Path(__file__).resolve().parents[1] / "app" / "gateway" / "services.py"


def _request(**state):
    base = {"user": SimpleNamespace(id="user-actor"), "actor_user_id": "user-actor", "auth_source": "session", "organization_id": "org-1"}
    return SimpleNamespace(state=SimpleNamespace(**(base | state)))


def _snapshot(**kw):
    args = {"content_user_id": "storage-shared", "thread_id": "thread-1", "portal_work_scope": {"client_id": "client-1", "project_id": None}, "runtime_context": {}}
    return rp.capture_admission_snapshot(kw.pop("request", _request()), **(args | kw))


def _receipt(**kw):
    return rp.build_receipt(_snapshot(**kw), "run-1", "2026-11-02T15:00:00+00:00")


def test_snapshot_uses_actor_not_storage_and_ignores_forged_config():
    forged = {"user_id": "user-forged", "actor_user_id": "user-forged", "client_id": "client-forged", "auth_source": "session"}
    snap = _snapshot(runtime_context=forged)
    assert snap["actor_user_id"] == "user-actor" and snap["storage_user_id"] == "storage-shared"
    assert snap["client_id"] == "client-1" and snap["origin"] == "session_http"
    with pytest.raises(TypeError):
        snap["actor_user_id"] = "x"  # frozen
    fallback = _snapshot(request=_request(actor_user_id=None))
    assert fallback["actor_user_id"] == "user-actor"  # authenticated user, never the storage alias
    assert _snapshot(request=_request(actor_user_id=None, user=None)) is None


@pytest.mark.parametrize(
    ("auth_source", "context", "origin"),
    [
        ("session", {}, "session_http"),
        ("session", {"is_subagent": True}, "session_noninteractive"),
        ("internal", {"channel_name": "slack"}, "internal_channel"),
        ("internal", {"non_interactive": True}, "internal_scheduled"),
        ("internal", {"is_subagent": True}, "internal_subagent"),
        ("pat", {}, "pat"),
        ("auth_disabled", {}, "auth_disabled"),
    ],
)
def test_origin_classification(auth_source, context, origin):
    assert _snapshot(request=_request(auth_source=auth_source), runtime_context=context)["origin"] == origin


def test_receipt_schema_is_bounded_and_secret_free():
    data = json.loads(_receipt())
    assert set(data) == set(rp.FIELDS) and data["protocol"] == rp.PROTOCOL and data["schema_version"] == 1
    assert _snapshot(request=_request(actor_user_id="person@example.test")) is None  # emails never ride in id slots
    assert _snapshot(portal_work_scope={"client_id": "x" * 200, "project_id": None}) is None
    with pytest.raises(ValueError):
        rp.build_receipt(_snapshot(), "../run", "2026-11-02T15:00:00+00:00")


def test_exclusive_race_identical_and_conflict(tmp_path):
    content = _receipt()
    results: list[str] = []
    barrier = threading.Barrier(8)

    def write():
        barrier.wait()
        results.append(rp.write_receipt(tmp_path, "run-1", content))

    threads = [threading.Thread(target=write) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == ["created"] + ["identical"] * 7
    final = tmp_path.joinpath(*rp.PRIVATE_PARTS)
    assert (final / "run-1.json").read_bytes() == content
    assert oct(final.stat().st_mode & 0o777) == "0o700" and oct((final / "run-1.json").stat().st_mode & 0o777) == "0o600"
    assert [p.name for p in final.iterdir()] == ["run-1.json"]  # temporaries removed
    with pytest.raises(rp.ProvenanceConflict):
        rp.write_receipt(tmp_path, "run-1", _receipt(content_user_id="storage-other"))
    assert (final / "run-1.json").read_bytes() == content  # original identity never replaced


def test_symlink_unsafe_id_and_mode_fail_closed(tmp_path):
    content = _receipt()
    with pytest.raises(ValueError):
        rp.write_receipt(tmp_path, "a/../b", content)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (tmp_path / "root").mkdir()
    os.symlink(elsewhere, tmp_path / "root" / "private")
    with pytest.raises(rp.ProvenanceUnavailable):
        rp.write_receipt(tmp_path / "root", "run-1", content)
    assert not any(elsewhere.iterdir())
    loose = tmp_path / "loose"
    loose.joinpath("private").mkdir(parents=True)
    os.chmod(loose / "private", 0o755)
    with pytest.raises(rp.ProvenanceUnavailable):
        rp.write_receipt(loose, "run-1", content)
    linked = tmp_path / "linked"
    final = linked.joinpath(*rp.PRIVATE_PARTS)
    final.mkdir(parents=True, mode=0o700)
    os.symlink(elsewhere / "target", final / "run-1.json")
    with pytest.raises(rp.ProvenanceConflict):
        rp.write_receipt(linked, "run-1", content)


def test_sink_failure_is_unknown_not_fatal(tmp_path, caplog):
    blocked = tmp_path / "file"
    blocked.write_text("")
    assert asyncio.run(rp.persist_new_run_receipt(_snapshot(), "run-1", "2026-11-02T15:00:00+00:00", root=blocked)) is None
    assert asyncio.run(rp.persist_new_run_receipt(None, "run-1", "2026-11-02T15:00:00+00:00", root=tmp_path)) is None
    assert not tmp_path.joinpath("private").exists()
    assert "user-actor" not in caplog.text and "storage-shared" not in caplog.text


def test_cancellation_drains_write_before_propagating(tmp_path, monkeypatch):
    started, release = threading.Event(), threading.Event()
    real = rp.write_receipt

    def slow(*args):
        started.set()
        release.wait(5)
        return real(*args)

    monkeypatch.setattr(rp, "write_receipt", slow)

    async def scenario():
        task = asyncio.create_task(rp.persist_new_run_receipt(_snapshot(), "run-1", "2026-11-02T15:00:00+00:00", root=tmp_path))
        await asyncio.to_thread(started.wait, 5)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()  # drained, not abandoned
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert tmp_path.joinpath(*rp.PRIVATE_PARTS, "run-1.json").exists()


def test_start_run_hook_order_preserves_reuse_and_no_await_gap():
    source = SERVICES.read_text(encoding="utf-8")
    worker = source[source.index("async def run_after_metadata(record: RunRecord) -> None:") :]
    first_statement = re.search(r"\n\s+(?!#)(\S.*)", worker).group(1)
    assert first_statement.startswith("await persist_new_run_receipt(provenance_snapshot, record.run_id, record.created_at)")
    admission = source[source.index("provenance_snapshot = capture_admission_snapshot(") : source.index("record.task = run_mgr.create_worker_task(")]
    assert "record = await run_mgr.create_or_reject(" in admission
    reuse = admission[admission.index("if record.idempotency_reused:") : admission.index("worker = run_after_metadata(record)")]
    assert reuse.rstrip().endswith("return record")  # reused runs are never restamped
    after_admission = admission[admission.index("worker = run_after_metadata(record)") :]
    assert "await" not in after_admission.split("\n", 2)[-1].replace("# No await is allowed", "")
    assert "body.config" not in source[source.index("provenance_snapshot = capture_admission_snapshot(") : source.index("record = await run_mgr.create_or_reject(")]
