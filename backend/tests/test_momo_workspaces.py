from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "fleet/workspaces/momo_workspaces.py"
spec = importlib.util.spec_from_file_location("momo_workspaces", SOURCE)
workspaces = importlib.util.module_from_spec(spec)
spec.loader.exec_module(workspaces)


class FakeDocker:
    def __init__(self):
        self.calls = []
        self.running = False

    def call(self, *args, capture=True):
        self.calls.append(args)
        if args[0] == "build":
            return ""
        if args[:2] == ("image", "inspect"):
            return json.dumps([{"Id": "sha256:base", "Architecture": "arm64", "Os": "linux", "RepoDigests": [], "Config": {"Labels": {workspaces.BASE_LABEL: "test-v1"}}}])
        if args[0] == "create":
            return "container-synthetic"
        if args[0] in {"volume", "run"}:
            return ""
        if args[0] == "cp":
            destination = Path(args[-1])
            if destination.name == "artifacts":
                (destination / "result.json").write_text('{"synthetic":true}\n')
                (destination / "link").symlink_to("/etc/passwd")
            return ""
        if args[0] == "inspect":
            env_id = args[1].removeprefix("momo-ws-")
            return json.dumps([{"Config": {"Labels": {workspaces.MANAGED: "true", workspaces.ENV_LABEL: env_id}}, "State": {"Status": "running" if self.running else "exited", "Running": self.running}}])
        if args[0] == "start":
            self.running = True
            return args[1]
        if args[0] == "stop":
            self.running = False
            return args[2]
        if args[0] == "exec":
            return json.dumps({"status": "completed", "receipt_sha256": "a" * 64})
        if args[:2] == ("system", "df"):
            return json.dumps({"Type": "Containers", "Size": "1MB"})
        if args[0] == "stats":
            return json.dumps({"MemUsage": "10MiB / 512MiB"})
        if args[0] == "rm":
            self.running = False
            return args[2]
        raise AssertionError(args)


class FakeOrb:
    def __init__(self):
        self.calls = []

    def call(self, *args, capture=True):
        self.calls.append(args)
        assert args[:3] == ("docker", "volume", "clone")
        return ""


@pytest.fixture
def manager(tmp_path):
    manager = workspaces.Manager(tmp_path / "state", docker=FakeDocker(), orb=FakeOrb(), min_free_bytes=0)
    manager.client_roots = {"synthetic-client": tmp_path / "client"}
    workspaces.atomic_json(manager.root / "base.json", {"image_id": "sha256:base", "architecture": "arm64", "golden_volume": "momobot-ws-golden-test"})
    return manager


def payload(job_id="job-1", client_id="synthetic-client"):
    return {"schema_version": 1, "job_id": job_id, "client_id": client_id, "attempt": 1, "command": ["python3", "-c", "print('synthetic')"], "timeout_seconds": 30}


def test_build_records_native_architecture_and_pinned_identity(tmp_path):
    manager = workspaces.Manager(tmp_path / "state", docker=FakeDocker(), min_free_bytes=0)
    result = manager.build()
    assert result["architecture"] == "arm64"
    assert result["image_id"] == "sha256:base"
    assert result["base_version"] == "test-v1"
    assert json.loads((manager.root / "base.json").read_text()) == result


def test_build_explicit_platform_is_forwarded_and_verified(tmp_path):
    manager = workspaces.Manager(tmp_path / "state", docker=FakeDocker(), min_free_bytes=0, platform="linux/amd64")
    with pytest.raises(workspaces.WorkspaceError, match="architecture_mismatch"):
        manager.build()
    args = manager.docker.calls[0]
    assert args[:2] == ("build", "--platform")
    assert args[2] == "linux/amd64"


def test_create_is_stopped_isolated_limited_and_networkless(manager):
    result = manager.create("pilot-001", "synthetic-client")
    assert result["state"] == "stopped"
    args = manager.docker.calls[-1]
    assert args[0] == "create"
    assert "--network" in args and args[args.index("--network") + 1] == "none"
    assert args[args.index("--memory") + 1] == "512m"
    assert args[args.index("--memory-swap") + 1] == "512m"
    assert "--cap-drop" in args and "ALL" in args
    assert "type=volume,src=momobot-ws-pilot-001-data,dst=/mnt/data" in args
    assert manager.orb.calls[-1] == ("docker", "volume", "clone", "momobot-ws-golden-test", "momobot-ws-pilot-001-data")
    assert result["volume"] == "momobot-ws-pilot-001-data"
    assert not manager.docker.running


def test_create_supports_explicit_read_only_client_mount(manager, tmp_path):
    client = tmp_path / "client"
    client.mkdir()
    manager.create("pilot-001", "synthetic-client", client)
    args = manager.docker.calls[-1]
    assert f"type=bind,src={client},dst=/mnt/client,readonly" in args


def test_client_scope_and_duplicate_job_conflict_fail_closed(manager):
    manager.create("pilot-001", "synthetic-client")
    with pytest.raises(workspaces.WorkspaceError, match="client_scope_mismatch"):
        manager.job("pilot-001", payload(client_id="other-client"))
    manager.job("pilot-001", payload())
    conflict = payload()
    conflict["command"] = ["python3", "-c", "print('changed')"]
    with pytest.raises(workspaces.WorkspaceError, match="duplicate_job_conflict"):
        manager.job("pilot-001", conflict)


def test_completed_duplicate_never_executes_twice(manager):
    manager.create("pilot-001", "synthetic-client")
    first = manager.job("pilot-001", payload())
    executions = len([call for call in manager.docker.calls if call[0] == "exec"])
    second = manager.job("pilot-001", payload())
    assert first["status"] == second["status"] == "completed"
    assert second["duplicate_suppressed"] is True
    assert len([call for call in manager.docker.calls if call[0] == "exec"]) == executions


def test_fourth_simultaneous_worker_is_rejected(manager):
    with manager.worker_slot("job-1"):
        with manager.worker_slot("job-2"):
            with manager.worker_slot("job-3"):
                with pytest.raises(workspaces.WorkspaceError, match="worker_limit_3"):
                    with manager.worker_slot("job-4"):
                        pass
            with manager.worker_slot("job-4") as slot:
                assert slot in {0, 1, 2}


def test_failure_stops_environment_and_recovery_requeues_without_running(manager):
    manager.create("pilot-001", "synthetic-client")
    original = manager.docker.call

    def fail_exec(*args, capture=True):
        if args[0] == "exec":
            raise workspaces.WorkspaceError("synthetic_failure")
        return original(*args, capture=capture)

    manager.docker.call = fail_exec
    with pytest.raises(workspaces.WorkspaceError, match="synthetic_failure"):
        manager.job("pilot-001", payload())
    assert manager.docker.running is False
    current = json.loads((manager.jobs / "job-1.json").read_text())
    current["status"] = "running"
    (manager.jobs / "job-1.json").write_text(json.dumps(current))
    recovered = manager.recover("pilot-001", "job-1")
    assert recovered[0]["status"] == "pending"
    assert manager.docker.running is False
    manager.docker.call = original
    resumed = manager.job("pilot-001", payload())
    assert resumed["status"] == "completed"
    assert "error" not in resumed


def test_save_hashes_only_regular_artifacts(manager):
    manager.create("pilot-001", "synthetic-client")
    result = manager.save("pilot-001")
    assert result["files"] == [{"path": "result.json", "bytes": 19, "sha256": __import__("hashlib").sha256(b'{"synthetic":true}\n').hexdigest()}]


def test_cleanup_requires_owned_record_and_container(manager, tmp_path):
    manager.create("pilot-001", "synthetic-client")
    assert manager.cleanup("pilot-001")["removed"] is True
    with pytest.raises(workspaces.WorkspaceError, match="environment_not_found"):
        manager.cleanup("pilot-001")
    outsider = tmp_path / "outsider"
    outsider.mkdir()
    with pytest.raises(workspaces.WorkspaceError, match="invalid_identifier"):
        manager.cleanup(str(outsider))


def test_measure_reports_zero_dormant_workers(manager):
    manager.create("pilot-001", "synthetic-client")
    result = manager.measure()
    assert result["active_owned_workers"] == 0
    assert result["saved_owned_environments"] == 1
    assert result["docker_stats"] == []


def test_client_mount_requires_trusted_root_and_resolved_containment(manager, tmp_path):
    admitted = tmp_path / "client"
    outsider = tmp_path / "outsider"
    admitted.mkdir()
    outsider.mkdir()
    with pytest.raises(workspaces.WorkspaceError, match="client_path_outside_admitted_root"):
        manager.create("pilot-001", "synthetic-client", outsider)
    escape = admitted / "escape"
    escape.symlink_to(outsider, target_is_directory=True)
    with pytest.raises(workspaces.WorkspaceError, match="client_path_outside_admitted_root"):
        manager.create("pilot-002", "synthetic-client", escape)
    manager.client_roots = {}
    with pytest.raises(workspaces.WorkspaceError, match="client_root_not_configured"):
        manager.create("pilot-003", "synthetic-client", admitted)
    assert manager.orb.calls == []


def test_stop_failure_retains_capacity_and_cleanup_retry_does_not_replay(manager):
    manager.create("pilot-001", "synthetic-client")
    original = manager.docker.call

    def fail_stop(*args, capture=True):
        if args[0] == "stop":
            raise workspaces.WorkspaceError("synthetic_stop_failure")
        return original(*args, capture=capture)

    manager.docker.call = fail_stop
    with pytest.raises(workspaces.WorkspaceError, match="synthetic_stop_failure"):
        manager.job("pilot-001", payload())
    current = json.loads((manager.jobs / "job-1.json").read_text())
    assert current["status"] == "cleanup_pending"
    assert current["command_status"] == "completed"
    assert manager.docker.running is True
    with manager.worker_slot("other-1"), manager.worker_slot("other-2"):
        with pytest.raises(workspaces.WorkspaceError, match="worker_limit_3"):
            with manager.worker_slot("other-3"):
                pass
    manager._release_retained_slot("pilot-001")
    restarted = workspaces.Manager(manager.root, docker=manager.docker, orb=manager.orb, min_free_bytes=0)
    with restarted.worker_slot("other-1"), restarted.worker_slot("other-2"):
        with pytest.raises(workspaces.WorkspaceError, match="worker_limit_3"):
            with restarted.worker_slot("other-3"):
                pass
    manager.docker.call = original
    resumed = restarted.job("pilot-001", payload())
    assert resumed["status"] == "completed"
    assert manager.docker.running is False
    assert len([call for call in manager.docker.calls if call[0] == "exec"]) == 1
    with restarted.worker_slot("other-1"), restarted.worker_slot("other-2"), restarted.worker_slot("other-3"):
        pass


def test_reused_environment_enforces_disk_floor_without_consuming_work(manager, monkeypatch):
    manager.create("pilot-001", "synthetic-client")
    manager.min_free_bytes = 1
    stat = type("Stat", (), {"f_bavail": 0, "f_frsize": 4096})()
    monkeypatch.setattr(workspaces.os, "statvfs", lambda _path: stat)
    with pytest.raises(workspaces.WorkspaceError, match="disk_headroom_below_1"):
        manager.job("pilot-001", payload())
    assert not [call for call in manager.docker.calls if call[0] == "exec"]
    manager.min_free_bytes = 0
    assert manager.job("pilot-001", payload())["status"] == "completed"


def test_recovery_respects_live_job_lock(manager):
    manager.create("pilot-001", "synthetic-client")
    manager.job("pilot-001", payload())
    path = manager.jobs / "job-1.json"
    current = json.loads(path.read_text())
    current["status"] = "running"
    current.pop("command_status", None)
    workspaces.atomic_json(path, current)
    stop_calls = len([call for call in manager.docker.calls if call[0] == "stop"])
    with manager.lock(manager.env_dir("pilot-001") / ".job.lock"):
        assert manager.recover("pilot-001", "job-1") == []
        assert json.loads(path.read_text())["status"] == "running"
        assert len([call for call in manager.docker.calls if call[0] == "stop"]) == stop_calls
    assert manager.recover("pilot-001", "job-1")[0]["status"] == "pending"


def test_retained_cleanup_rejects_different_job_until_exact_cleanup(manager):
    manager.create("pilot-001", "synthetic-client")
    original = manager.docker.call

    def fail_stop(*args, capture=True):
        if args[0] == "stop":
            raise workspaces.WorkspaceError("synthetic_stop_failure")
        return original(*args, capture=capture)

    manager.docker.call = fail_stop
    with pytest.raises(workspaces.WorkspaceError, match="synthetic_stop_failure"):
        manager.job("pilot-001", payload("old-job"))
    manager.docker.call = original
    with pytest.raises(workspaces.WorkspaceError, match="environment_cleanup_pending"):
        manager.job("pilot-001", payload("new-job"))
    assert len([call for call in manager.docker.calls if call[0] == "exec"]) == 1
    assert json.loads((manager.jobs / "old-job.json").read_text())["status"] == "cleanup_pending"
    assert json.loads((manager.jobs / "new-job.json").read_text())["status"] == "pending"
    recovered = manager.recover("pilot-001", "old-job")
    assert recovered[0]["status"] == "completed"
    assert len([call for call in manager.docker.calls if call[0] == "exec"]) == 1
    assert manager.job("pilot-001", payload("new-job"))["status"] == "completed"
    assert len([call for call in manager.docker.calls if call[0] == "exec"]) == 2
    with manager.worker_slot("other-1"), manager.worker_slot("other-2"), manager.worker_slot("other-3"):
        pass


def test_independent_recovery_reuses_exact_reservation_without_extra_capacity(manager):
    import subprocess
    import sys

    original = manager.docker.call

    def fail_stop(*args, capture=True):
        if args[0] == "stop":
            raise workspaces.WorkspaceError("synthetic_stop_failure")
        return original(*args, capture=capture)

    manager.docker.call = fail_stop
    for index in range(3):
        env_id = f"pilot-{index:03d}"
        manager.create(env_id, "synthetic-client")
        with pytest.raises(workspaces.WorkspaceError, match="synthetic_stop_failure"):
            manager.job(env_id, payload(f"blocked-{index}"))
    manager.docker.call = original
    assert len(manager._retained_slots) == 3
    child = r"""
import importlib.util
import json
import sys
from pathlib import Path

source, root, env_id, job_id, outcome = sys.argv[1:]
spec = importlib.util.spec_from_file_location("momo_workspaces_recovery", source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class RecoveryDocker:
    def __init__(self):
        self.calls = []

    def call(self, *args, capture=True):
        self.calls.append(args)
        if args[0] == "inspect":
            env_id = args[1].removeprefix("momo-ws-")
            return json.dumps([{"Config": {"Labels": {module.MANAGED: "true", module.ENV_LABEL: env_id}}}])
        if args[0] == "stop":
            if outcome == "fail":
                raise module.WorkspaceError("synthetic_recovery_stop_failure")
            return args[2]
        raise AssertionError(args)


docker = RecoveryDocker()
manager = module.Manager(Path(root), docker=docker, min_free_bytes=0)
result = manager.recover(env_id, job_id)
print(json.dumps({"status": result[0]["status"], "calls": docker.calls}))
"""

    def recover(env_id, job_id, outcome="ok"):
        return subprocess.run(
            [sys.executable, "-c", child, str(SOURCE), str(manager.root), env_id, job_id, outcome],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

    recovered = recover("pilot-000", "blocked-0")
    assert recovered.returncode == 0, recovered.stderr
    result = json.loads(recovered.stdout)
    assert result["status"] == "completed"
    assert result["calls"] == [["inspect", "momo-ws-pilot-000"], ["stop", "--time", "10", "momo-ws-pilot-000"]]
    failed = recover("pilot-001", "blocked-1", "fail")
    assert failed.returncode != 0
    assert "synthetic_recovery_stop_failure" in failed.stderr
    assert json.loads((manager.jobs / "blocked-1.json").read_text())["status"] == "cleanup_pending"
    assert len(manager._retained_slots) == 3
    restarted = workspaces.Manager(manager.root, docker=manager.docker, orb=manager.orb, min_free_bytes=0)
    with restarted.worker_slot("after-recovery"):
        with pytest.raises(workspaces.WorkspaceError, match="worker_limit_3"):
            with restarted.worker_slot("after-limit"):
                pass
