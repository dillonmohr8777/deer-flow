#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
ENV_ID = re.compile(r"^[a-z][a-z0-9-]{1,62}$")
MANAGED = "com.momobot.workspace.managed"
ENV_LABEL = "com.momobot.workspace.id"
CLIENT_LABEL = "com.momobot.workspace.client"
BASE_LABEL = "com.momobot.workspace.base-version"
DEFAULT_IMAGE = "momobot/linux-workspace:2026.10.25-1"
JOB_FIELDS = {"schema_version", "job_id", "client_id", "attempt", "command", "timeout_seconds"}


class WorkspaceError(RuntimeError):
    pass


def now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha256(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def atomic_json(path: Path, value: dict, *, exclusive: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if exclusive:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(canonical(value).decode() + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        return
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(canonical(value).decode() + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def valid_id(value: str, *, environment: bool = False) -> str:
    pattern = ENV_ID if environment else ID
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise WorkspaceError("invalid_identifier")
    return value


class Command:
    executable = "docker"

    def call(self, *args: str, capture: bool = True) -> str:
        command = [self.executable, *args]
        result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE if capture else None, stderr=subprocess.PIPE, check=False)
        if result.returncode != 0:
            detail = (result.stderr or b"").decode(errors="replace")[-2000:]
            raise WorkspaceError(f"{self.executable}_failed:{args[0]}:{detail.strip()}")
        return (result.stdout or b"").decode().strip()


class Docker(Command):
    pass


class Orb(Command):
    executable = "orb"


class Manager:
    def __init__(self, root: Path, image: str = DEFAULT_IMAGE, docker: Docker | None = None, orb: Orb | None = None, min_free_bytes: int = 8 * 1024**3, platform: str | None = None, client_roots: dict[str, str | Path] | None = None):
        if platform is not None and platform not in {"linux/arm64", "linux/amd64"}:
            raise WorkspaceError("unsupported_workspace_platform")
        self.root = root
        self.image = image
        self.platform = platform
        self.docker = docker or Docker()
        self.orb = orb or Orb()
        self.min_free_bytes = min_free_bytes
        self.client_roots = {valid_id(client): Path(path) for client, path in (client_roots or {}).items()}
        self._retained_slots: dict[str, tuple[int, int]] = {}
        self.environments = root / "environments"
        self.jobs = root / "jobs"
        self.slots = root / "slots"
        for directory in (root, self.environments, self.jobs, self.slots):
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)

    @contextmanager
    def lock(self, path: Path, *, blocking: bool = True):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield descriptor
        finally:
            os.close(descriptor)

    def _slot_job_status(self, job_id: str) -> str:
        if not ID.fullmatch(job_id):
            return "unknown"
        try:
            return json.loads((self.jobs / f"{job_id}.json").read_text(encoding="utf-8")).get("status", "unknown")
        except FileNotFoundError:
            return "stopped"
        except (OSError, ValueError, AttributeError):
            return "unknown"

    @contextmanager
    def worker_slot(self, job_id: str, *, retain_on_exit: list[str] | None = None):
        with self.lock(self.slots / ".admission.lock"):
            acquired = None
            for index in range(3):
                path = self.slots / f"worker-{index}.lock"
                descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    previous = os.read(descriptor, 129).decode(errors="replace").strip()
                    if previous and previous != job_id and self._slot_job_status(previous) in {"running", "cleanup_pending", "unknown"}:
                        os.close(descriptor)
                        continue
                    acquired = (index, descriptor)
                    break
                except BlockingIOError:
                    os.close(descriptor)
            if acquired is None:
                raise WorkspaceError("worker_limit_3")
            index, descriptor = acquired
            try:
                os.ftruncate(descriptor, 0)
                os.lseek(descriptor, 0, os.SEEK_SET)
                os.write(descriptor, f"{job_id}\n".encode())
                os.fsync(descriptor)
            except BaseException:
                os.close(descriptor)
                raise
        try:
            yield index
        finally:
            if retain_on_exit:
                self._retained_slots[retain_on_exit[0]] = (index, descriptor)
            else:
                os.close(descriptor)

    @contextmanager
    def job_slot(self, env_id: str, job_id: str, retain_on_exit: list[str]):
        # The caller holds the environment execution lock across this durable owner check.
        for path in self.jobs.glob("*.json"):
            current = json.loads(path.read_text(encoding="utf-8"))
            if current.get("env_id") == env_id and current.get("job_id") != job_id and current.get("status") in {"running", "cleanup_pending"}:
                raise WorkspaceError("environment_cleanup_pending")
        retained = self._retained_slots.get(env_id)
        if retained is not None:
            owner = os.pread(retained[1], 129, 0).decode(errors="replace").strip()
            status = self._slot_job_status(owner)
            if owner != job_id or status not in {"running", "cleanup_pending", "unknown"}:
                if status in {"running", "cleanup_pending", "unknown"}:
                    raise WorkspaceError("environment_cleanup_pending")
                self._release_retained_slot(env_id)
            else:
                yield retained[0]
                return
        with self.worker_slot(job_id, retain_on_exit=retain_on_exit) as index:
            yield index

    @contextmanager
    def cleanup_slot(self, job_id: str):
        # Admission opens, locks and rewrites slot generations only inside this fence.
        with self.lock(self.slots / ".admission.lock"):
            reservations = []
            try:
                for index in range(3):
                    path = self.slots / f"worker-{index}.lock"
                    try:
                        descriptor = os.open(path, os.O_RDWR)
                    except FileNotFoundError:
                        continue
                    owner = os.pread(descriptor, 129, 0).decode(errors="replace").strip()
                    if owner != job_id:
                        os.close(descriptor)
                        continue
                    stat = os.fstat(descriptor)
                    reservations.append((path, descriptor, stat.st_dev, stat.st_ino))
                if not reservations:
                    raise WorkspaceError("worker_reservation_not_found")
                yield
                for path, descriptor, device, inode in reservations:
                    try:
                        current = os.stat(path)
                    except FileNotFoundError:
                        continue
                    if (current.st_dev, current.st_ino) == (device, inode):
                        path.unlink()
            finally:
                for _, descriptor, _, _ in reservations:
                    os.close(descriptor)

    def _release_retained_slot(self, env_id: str) -> None:
        retained = self._retained_slots.pop(env_id, None)
        if retained is not None:
            os.close(retained[1])

    def env_dir(self, env_id: str) -> Path:
        return self.environments / valid_id(env_id, environment=True)

    def env_record(self, env_id: str) -> dict:
        path = self.env_dir(env_id) / "environment.json"
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise WorkspaceError("environment_not_found") from None
        if value.get("env_id") != env_id or value.get("managed") is not True:
            raise WorkspaceError("environment_ownership_mismatch")
        return value

    def container(self, env_id: str) -> str:
        return f"momo-ws-{env_id}"

    def inspect(self, env_id: str) -> dict:
        raw = self.docker.call("inspect", self.container(env_id))
        values = json.loads(raw)
        if not isinstance(values, list) or len(values) != 1:
            raise WorkspaceError("environment_not_found")
        value = values[0]
        labels = value.get("Config", {}).get("Labels", {})
        if labels.get(MANAGED) != "true" or labels.get(ENV_LABEL) != env_id:
            raise WorkspaceError("environment_ownership_mismatch")
        return value

    def assert_free_headroom(self) -> None:
        usage = self.docker.call("system", "df", "--format", "{{json .}}")
        del usage
        stat = os.statvfs(self.root)
        free = stat.f_bavail * stat.f_frsize
        if free < self.min_free_bytes:
            raise WorkspaceError(f"disk_headroom_below_{self.min_free_bytes}")

    def build(self) -> dict:
        source = Path(__file__).resolve().parent
        args = ["build"]
        if self.platform:
            args.extend(["--platform", self.platform])
        args.extend(["--file", str(source / "Dockerfile"), "--tag", self.image, str(source)])
        self.docker.call(*args, capture=False)
        image = json.loads(self.docker.call("image", "inspect", self.image))[0]
        record = {
            "schema_version": 1,
            "image": self.image,
            "image_id": image["Id"],
            "architecture": image["Architecture"],
            "os": image["Os"],
            "base_version": image.get("Config", {}).get("Labels", {}).get(BASE_LABEL),
            "repo_digests": image.get("RepoDigests", []),
            "built_at": now(),
        }
        if record["os"] != "linux" or record["architecture"] not in {"arm64", "amd64"}:
            raise WorkspaceError("unsupported_workspace_architecture")
        record["platform"] = f"linux/{record['architecture']}"
        if self.platform is not None and record["platform"] != self.platform:
            raise WorkspaceError("workspace_architecture_mismatch")
        record["golden_volume"] = f"momobot-ws-golden-{record['base_version']}"
        self.docker.call("volume", "create", "--label", f"{MANAGED}=true", "--label", f"{BASE_LABEL}={record['base_version']}", record["golden_volume"])
        self.docker.call(
            "run",
            "--rm",
            *(["--platform", self.platform] if self.platform else []),
            "--network",
            "none",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--mount",
            f"type=volume,src={record['golden_volume']},dst=/mnt/data",
            self.image,
            "python3",
            "-c",
            "from pathlib import Path; [Path('/mnt/data', name).mkdir(exist_ok=True) for name in ('artifacts', 'checkpoints', 'receipts', 'logs')]",
        )
        atomic_json(self.root / "base.json", record)
        return record

    def base(self) -> dict:
        try:
            return json.loads((self.root / "base.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise WorkspaceError("base_not_built") from None

    def volume(self, env_id: str) -> str:
        return f"momobot-ws-{valid_id(env_id, environment=True)}-data"

    def client_mount(self, client_id: str, client_path: Path) -> Path:
        configured = self.client_roots.get(client_id)
        if configured is None:
            raise WorkspaceError("client_root_not_configured")
        if not configured.is_absolute() or not client_path.is_absolute():
            raise WorkspaceError("client_path_not_absolute")
        try:
            root = configured.resolve(strict=True)
            resolved = client_path.resolve(strict=True)
        except (OSError, RuntimeError):
            raise WorkspaceError("client_path_unavailable") from None
        if not root.is_dir() or not resolved.is_dir():
            raise WorkspaceError("client_path_not_directory")
        if not resolved.is_relative_to(root):
            raise WorkspaceError("client_path_outside_admitted_root")
        return resolved

    def create(self, env_id: str, client_id: str, client_path: Path | None = None) -> dict:
        valid_id(env_id, environment=True)
        valid_id(client_id)
        resolved = self.client_mount(client_id, client_path) if client_path is not None else None
        self.assert_free_headroom()
        base = self.base()
        with self.lock(self.env_dir(env_id) / ".create.lock"):
            record_path = self.env_dir(env_id) / "environment.json"
            if record_path.exists():
                raise WorkspaceError("environment_exists")
            volume = self.volume(env_id)
            self.orb.call("docker", "volume", "clone", base["golden_volume"], volume)
            args = [
                "create",
                "--init",
                "--name",
                self.container(env_id),
                "--label",
                f"{MANAGED}=true",
                "--label",
                f"{ENV_LABEL}={env_id}",
                "--label",
                f"{CLIENT_LABEL}={client_id}",
                "--memory",
                "512m",
                "--memory-swap",
                "512m",
                "--cpus",
                "1",
                "--pids-limit",
                "128",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--network",
                "none",
                "--mount",
                f"type=volume,src={volume},dst=/mnt/data",
            ]
            if resolved is not None:
                args.extend(["--mount", f"type=bind,src={resolved},dst=/mnt/client,readonly"])
            args.extend([self.image, "sleep", "infinity"])
            container_id = self.docker.call(*args)
            record = {
                "schema_version": 1,
                "managed": True,
                "env_id": env_id,
                "client_id": client_id,
                "container": self.container(env_id),
                "container_id": container_id,
                "volume": volume,
                "image": self.image,
                "image_id": base["image_id"],
                "architecture": base["architecture"],
                "state": "stopped",
                "created_at": now(),
                "updated_at": now(),
            }
            atomic_json(record_path, record, exclusive=True)
            return record

    def start(self, env_id: str) -> dict:
        record = self.env_record(env_id)
        self.inspect(env_id)
        self.assert_free_headroom()
        started = time.monotonic()
        self.docker.call("start", self.container(env_id))
        record.update(state="running", updated_at=now(), last_start_seconds=round(time.monotonic() - started, 3))
        atomic_json(self.env_dir(env_id) / "environment.json", record)
        return record

    def stop(self, env_id: str) -> dict:
        record = self.env_record(env_id)
        self.inspect(env_id)
        started = time.monotonic()
        self.docker.call("stop", "--time", "10", self.container(env_id))
        record.update(state="stopped", updated_at=now(), last_stop_seconds=round(time.monotonic() - started, 3))
        atomic_json(self.env_dir(env_id) / "environment.json", record)
        self._release_retained_slot(env_id)
        return record

    def status(self) -> list[dict]:
        results = []
        for path in sorted(self.environments.glob("*/environment.json")):
            env_id = path.parent.name
            record = self.env_record(env_id)
            inspected = self.inspect(env_id)
            record["docker_state"] = inspected.get("State", {}).get("Status", "unknown")
            record["docker_running"] = inspected.get("State", {}).get("Running") is True
            results.append(record)
        return results

    def job(self, env_id: str, payload: dict) -> dict:
        if not isinstance(payload, dict) or set(payload) != JOB_FIELDS or payload.get("schema_version") != 1:
            raise WorkspaceError("invalid_job_schema")
        job_id = valid_id(payload["job_id"])
        client_id = valid_id(payload["client_id"])
        if type(payload["attempt"]) is not int or not 1 <= payload["attempt"] <= 100:
            raise WorkspaceError("invalid_job_attempt")
        if type(payload["timeout_seconds"]) is not int or not 1 <= payload["timeout_seconds"] <= 3600:
            raise WorkspaceError("invalid_job_timeout")
        command = payload["command"]
        if not isinstance(command, list) or not 1 <= len(command) <= 32 or any(not isinstance(part, str) or not part or len(part) > 8192 for part in command):
            raise WorkspaceError("invalid_job_command")
        record = self.env_record(env_id)
        if record["client_id"] != client_id:
            raise WorkspaceError("client_scope_mismatch")
        fingerprint = sha256({**payload, "attempt": 0})
        job_path = self.jobs / f"{job_id}.json"
        existing = {
            "schema_version": 1,
            "job_id": job_id,
            "client_id": client_id,
            "env_id": env_id,
            "request_sha256": fingerprint,
            "status": "pending",
            "created_at": now(),
            "updated_at": now(),
        }
        try:
            atomic_json(job_path, existing, exclusive=True)
        except FileExistsError:
            current = json.loads(job_path.read_text(encoding="utf-8"))
            if current.get("request_sha256") != fingerprint or current.get("env_id") != env_id:
                raise WorkspaceError("duplicate_job_conflict") from None
            if current.get("status") == "completed":
                return {**current, "duplicate_suppressed": True}
            if current.get("status") == "running":
                return {**current, "duplicate_suppressed": True, "execution_unchanged": True}
            if current.get("status") != "cleanup_pending":
                existing = {**current, "status": "pending", "updated_at": now()}
                atomic_json(job_path, existing)
        retention = []
        with self.lock(self.env_dir(env_id) / ".job.lock"), self.job_slot(env_id, job_id, retention):
            current = json.loads(job_path.read_text(encoding="utf-8"))
            if current.get("status") == "completed":
                return {**current, "duplicate_suppressed": True}
            if current.get("status") == "running":
                return {**current, "duplicate_suppressed": True, "execution_unchanged": True}
            command_error = None
            if current.get("status") != "cleanup_pending":
                current.pop("error", None)
                current.pop("finished_at", None)
                current.pop("command_status", None)
                current.pop("cleanup_error", None)
                current.update(status="running", started_at=now(), updated_at=now())
                atomic_json(job_path, current)
                staged_payload = self.env_dir(env_id) / "job.json"
                atomic_json(staged_payload, payload)
                staged_payload.chmod(0o644)
                try:
                    self.docker.call("cp", str(staged_payload), f"{self.container(env_id)}:/mnt/data/job.json")
                    self.start(env_id)
                    output = self.docker.call(
                        "exec",
                        "--env",
                        f"MOMO_JOB_ID={job_id}",
                        "--env",
                        f"MOMO_CLIENT_ID={client_id}",
                        self.container(env_id),
                        "python3",
                        "/opt/momobot/job_runner.py",
                        "/mnt/data/job.json",
                    )
                    command_status = "completed"
                    current.update(command_status=command_status, runner_output=json.loads(output.splitlines()[-1]))
                except Exception as error:
                    command_error = error
                    command_status = "failed"
                    current.update(command_status=command_status, error=str(error)[:500])
                current.update(status="cleanup_pending", updated_at=now())
                atomic_json(job_path, current)
            try:
                self.stop(env_id)
            except Exception as error:
                retention.append(env_id)
                current.update(status="cleanup_pending", cleanup_error=str(error)[:500], updated_at=now())
                atomic_json(job_path, current)
                if command_error is not None:
                    raise command_error
                raise
            final_status = {"completed": "completed", "failed": "failed"}.get(current.get("command_status"), "pending")
            current.pop("cleanup_error", None)
            if final_status == "pending":
                current.pop("finished_at", None)
                current.update(status="pending", recovered_at=now(), updated_at=now())
            else:
                current.update(status=final_status, finished_at=now(), updated_at=now())
            atomic_json(job_path, current)
            if command_error is not None:
                raise command_error
            if final_status == "failed":
                raise WorkspaceError(current.get("error", "workspace_job_failed"))
            return current

    def recover(self, env_id: str, job_id: str) -> list[dict]:
        valid_id(env_id, environment=True)
        valid_id(job_id)
        path = self.jobs / f"{job_id}.json"
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise WorkspaceError("job_not_found") from None
        if current.get("job_id") != job_id or current.get("env_id") != env_id:
            raise WorkspaceError("recovery_scope_mismatch")
        try:
            with self.lock(self.env_dir(env_id) / ".job.lock", blocking=False):
                current = json.loads(path.read_text(encoding="utf-8"))
                if current.get("job_id") != job_id or current.get("env_id") != env_id:
                    raise WorkspaceError("recovery_scope_mismatch")
                if current.get("status") not in {"running", "cleanup_pending"}:
                    return [current]
                try:
                    self.stop(env_id)
                except Exception as error:
                    current.update(status="cleanup_pending", command_status=current.get("command_status", "interrupted"), cleanup_error=str(error)[:500], updated_at=now())
                    atomic_json(path, current)
                    raise
                with self.cleanup_slot(job_id):
                    final_status = "completed" if current.get("command_status") == "completed" else "pending"
                    current.pop("cleanup_error", None)
                    if final_status == "pending":
                        current.pop("finished_at", None)
                    current.update(status=final_status, recovered_at=now(), updated_at=now())
                    atomic_json(path, current)
                    return [current]
        except BlockingIOError:
            return []

    def save(self, env_id: str) -> dict:
        record = self.env_record(env_id)
        export = Path(tempfile.mkdtemp(prefix="save-", dir=self.env_dir(env_id)))
        artifacts = export / "artifacts"
        artifacts.mkdir()
        self.docker.call("cp", f"{self.container(env_id)}:/mnt/data/artifacts/.", str(artifacts))
        files = []
        for path in sorted(artifacts.rglob("*")):
            if path.is_file() and not path.is_symlink():
                raw = path.read_bytes()
                files.append({"path": str(path.relative_to(artifacts)), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
        manifest = {"schema_version": 1, "env_id": env_id, "client_id": record["client_id"], "saved_at": now(), "export": str(export), "files": files}
        atomic_json(self.env_dir(env_id) / "artifact-manifest.json", manifest)
        return manifest

    def cleanup(self, env_id: str) -> dict:
        record = self.env_record(env_id)
        self.inspect(env_id)
        self.docker.call("rm", "--force", self.container(env_id))
        self.docker.call("volume", "rm", record["volume"])
        shutil.rmtree(self.env_dir(env_id))
        return {"env_id": env_id, "removed": True, "client_id": record["client_id"]}

    def measure(self) -> dict:
        disk_rows = [json.loads(line) for line in self.docker.call("system", "df", "--format", "{{json .}}").splitlines()]
        running = [record["env_id"] for record in self.status() if record["docker_running"]]
        stats = []
        if running:
            raw = self.docker.call("stats", "--no-stream", "--format", "{{json .}}", *[self.container(env_id) for env_id in running])
            stats = [json.loads(line) for line in raw.splitlines()]
        stat = os.statvfs(self.root)
        memory = {"platform": sys.platform}
        if sys.platform == "darwin":
            pressure = subprocess.run(["memory_pressure"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False, text=True).stdout
            swap = subprocess.run(["sysctl", "-n", "vm.swapusage"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False, text=True).stdout.strip()
            physical = subprocess.run(["sysctl", "-n", "hw.memsize"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False, text=True).stdout.strip()
            processes = subprocess.run(["ps", "-axo", "rss=,comm="], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False, text=True).stdout
            memory.update(
                physical_bytes=int(physical) if physical.isdigit() else None,
                free_percentage=int(match.group(1)) if (match := re.search(r"free percentage:\s*(\d+)%", pressure)) else None,
                swap=swap,
                orbstack_helper_rss_bytes=sum(int(line.split(None, 1)[0]) * 1024 for line in processes.splitlines() if "OrbStack Helper" in line),
            )
        elif sys.platform == "linux":
            values = {}
            for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
                key, raw = line.split(":", 1)
                values[key] = int(raw.strip().split()[0]) * 1024
            memory.update(physical_bytes=values.get("MemTotal"), available_bytes=values.get("MemAvailable"), free_bytes=values.get("MemFree"), swap_total_bytes=values.get("SwapTotal"), swap_free_bytes=values.get("SwapFree"))
        return {
            "captured_at": now(),
            "active_owned_workers": len(running),
            "saved_owned_environments": len(self.status()),
            "host_free_bytes": stat.f_bavail * stat.f_frsize,
            "host_memory": memory,
            "docker_df": disk_rows,
            "docker_df_verbose": self.docker.call("system", "df", "-v"),
            "docker_stats": stats,
        }


def load_payload(path: str) -> dict:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise WorkspaceError("invalid_job_file") from None
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Owned, stopped-by-default MomoBot Linux workspaces")
    parser.add_argument("--root", type=Path, default=Path.home() / ".local/state/momobot-linux-workspaces")
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    parser.add_argument("--platform", choices=("linux/arm64", "linux/amd64"))
    parser.add_argument("--client-root", action="append", default=[], metavar="CLIENT_ID=PATH")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("build")
    create = commands.add_parser("create")
    create.add_argument("env_id")
    create.add_argument("client_id")
    create.add_argument("--client-path", type=Path)
    batch = commands.add_parser("batch")
    batch.add_argument("prefix")
    batch.add_argument("client_id")
    batch.add_argument("--count", type=int, required=True)
    batch.add_argument("--start-index", type=int, default=1)
    for name in ("start", "stop", "save", "cleanup"):
        command = commands.add_parser(name)
        command.add_argument("env_id")
    job = commands.add_parser("job")
    job.add_argument("env_id")
    job.add_argument("payload")
    commands.add_parser("status")
    recover = commands.add_parser("recover")
    recover.add_argument("env_id")
    recover.add_argument("job_id")
    commands.add_parser("measure")
    args = parser.parse_args(argv)
    client_roots = {}
    for value in args.client_root:
        client_id, separator, path = value.partition("=")
        if not separator or not path or client_id in client_roots:
            raise WorkspaceError("invalid_client_root")
        client_roots[valid_id(client_id)] = Path(path)
    manager = Manager(args.root, args.image, platform=args.platform, client_roots=client_roots)
    if args.command == "build":
        result = manager.build()
    elif args.command == "create":
        result = manager.create(args.env_id, args.client_id, args.client_path)
    elif args.command == "batch":
        if not 1 <= args.count <= 100 or not 1 <= args.start_index <= 100 or args.start_index + args.count - 1 > 100:
            raise WorkspaceError("invalid_batch_range")
        result = [manager.create(f"{args.prefix}-{index:03d}", args.client_id) for index in range(args.start_index, args.start_index + args.count)]
    elif args.command == "job":
        result = manager.job(args.env_id, load_payload(args.payload))
    elif args.command == "status":
        result = manager.status()
    elif args.command == "recover":
        result = manager.recover(args.env_id, args.job_id)
    elif args.command == "measure":
        result = manager.measure()
    else:
        result = getattr(manager, args.command)(args.env_id)
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except WorkspaceError as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        raise SystemExit(1)
