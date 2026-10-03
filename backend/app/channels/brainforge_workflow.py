"""Read-only Brain Forge workflow using the existing pinned cloud brief builder.

This is an MomoBot channel workflow, not a new queue, model runtime or scheduler.
Only count projections reach Slack; the source brief stays in private storage.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BRIEF_MODULES = frozenset({"daily_brief.py", "checkpoint.py", "brief_items.py"})
SOURCE_FILES = frozenset({"registry/clients.json", "queue/work-items.json"})


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _private_directory(path: Path) -> None:
    if path.is_symlink():
        raise ValueError("private output path must not be a symlink")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)


def _pins(root: Path, expected: dict[str, str], names: frozenset[str]) -> dict[str, str]:
    if set(expected) != names or any(not re.fullmatch(r"[0-9a-f]{64}", value) for value in expected.values()):
        raise ValueError("complete source hash pins are required")
    actual = {}
    for name in sorted(names):
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("pinned source file is missing or a symlink")
        actual[name] = _digest(path.read_bytes())
    if actual != expected:
        raise ValueError("source drift: reviewed hash pins no longer match")
    return actual


@dataclass(frozen=True)
class BriefResult:
    text: str
    receipt_path: str
    receipt_sha256: str
    artifact_sha256: str
    queue_revision: int
    counts: dict[str, Any]


class BrainForgeBriefWorkflow:
    """Execute one deterministic workflow. No model, network, shell or queue writes."""

    def __init__(self, config: dict[str, Any]) -> None:
        for key in ("brief_source", "canonical_root", "artifact_root"):
            raw = Path(config[key]).absolute()
            if raw.is_symlink() or any(parent.is_symlink() for parent in raw.parents):
                raise ValueError("workflow paths must not traverse symlinks")
        self.source = Path(config["brief_source"]).resolve()
        self.canonical = Path(config["canonical_root"]).resolve()
        self.output = Path(config["artifact_root"]).resolve()
        self.module_hashes = dict(config["brief_source_hashes"])
        self.source_hashes = dict(config["source_hashes"])
        # Artifact writes must never land in either authoritative source tree.
        if self.output.is_relative_to(self.canonical) or self.output.is_relative_to(self.source):
            raise ValueError("artifact storage must be outside source trees")
        self.validate()

    def validate(self) -> None:
        _pins(self.source, self.module_hashes, BRIEF_MODULES)
        _pins(self.canonical, self.source_hashes, SOURCE_FILES)

    def run(self, *, job_key: str, client_id: str, thread_sha256: str) -> BriefResult:
        self.validate()
        if not re.fullmatch(r"[0-9a-f]{64}", thread_sha256):
            raise ValueError("verified thread hash required")
        recorded_ids = {row["id"] for row in json.loads((self.canonical / "registry/clients.json").read_bytes())["clients"]}
        if client_id != "__owner__" and client_id not in recorded_ids:
            raise ValueError("client route doesn't resolve to the pinned registry")
        _private_directory(self.output)
        job_dir = self.output / _digest(job_key.encode())
        _private_directory(job_dir)
        build = subprocess.run(
            [sys.executable, "-B", "-s", str(self.source / "daily_brief.py"), "build", "--root", str(self.canonical), "--out", str(job_dir)],
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
            env={"PATH": os.defpath, "LANG": "C.UTF-8"},
        )
        if build.returncode:
            raise ValueError("existing brief build failed; no completion claimed")
        proof = json.loads(build.stdout)
        manifest_path = Path(proof["manifestPath"])
        manifest_raw = manifest_path.read_bytes()
        if _digest(manifest_raw) != proof["manifestSha256"]:
            raise ValueError("manifest readback failed")
        manifest = json.loads(manifest_raw)
        # The existing read path checks source drift and snapshot/brief tampering.
        read = subprocess.run(
            [sys.executable, "-B", "-s", str(self.source / "daily_brief.py"), "read", "--manifest", str(manifest_path), "--expected-manifest-sha256", proof["manifestSha256"]],
            capture_output=True,
            timeout=30,
            check=False,
            env={"PATH": os.defpath, "LANG": "C.UTF-8"},
        )
        if read.returncode or _digest(read.stdout) != proof["artifactSha256"]:
            raise ValueError("protected brief readback failed")
        snapshot_path = Path(manifest["snapshot"]["path"])
        snapshot_raw = snapshot_path.read_bytes()
        if _digest(snapshot_raw) != manifest["snapshot"]["sha256"]:
            raise ValueError("snapshot readback failed")
        snap = json.loads(snapshot_raw)
        known = {row["id"] for row in snap["clients"]}
        if client_id != "__owner__" and client_id not in known:
            raise ValueError("client route doesn't resolve to the pinned registry")
        items = [row for row in snap["workItems"] if client_id == "__owner__" or row.get("clientId") == client_id]
        statuses = dict(sorted(Counter(row.get("status", "unknown") for row in items).items()))
        counts = {
            "workItems": len(items),
            "statuses": statuses,
            "nonterminal": sum(n for status, n in statuses.items() if status not in {"done", "cancelled"}),
            "unresolvedRoutes": sum(row.get("routingResolution") != "resolved_exact_registry_id" for row in items),
        }
        self.validate()
        receipt = {
            "kind": "brain_forge_read_only_workflow_receipt",
            "clientId": client_id,
            "jobKeySha256": _digest(job_key.encode()),
            "threadSha256": thread_sha256,
            "queueRevision": proof["sourceQueueRevision"],
            "sourceHead": proof["sourceHead"],
            "sourceHashes": self.source_hashes,
            "briefSourceHashes": self.module_hashes,
            "artifactSha256": proof["artifactSha256"],
            "manifestPath": str(manifest_path),
            "manifestSha256": proof["manifestSha256"],
            "counts": counts,
            "readbackVerified": True,
            "inputsUnchanged": True,
            "freshness": "pinned restored-source snapshot; not latest operations or live-service verification",
            "owner": "existing Chief; no canonical mutation",
            "cost": "zero provider calls",
        }
        raw = (json.dumps(receipt, sort_keys=True, indent=2) + "\n").encode()
        # Unique filename avoids overwriting an earlier proof on a recovery run.
        receipt_path = job_dir / ("workflow-" + proof["manifestSha256"] + ".json")
        with os.fdopen(os.open(receipt_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if receipt_path.read_bytes() != raw:
            raise ValueError("workflow receipt readback failed")
        line = ", ".join(f"{key}: {value}" for key, value in statuses.items()) or "no recorded items"
        text = "\n".join(
            [
                "Brain Forge verified work brief",
                f"Recorded route: {client_id}; queue revision {proof['sourceQueueRevision']}.",
                f"Work items: {len(items)}; nonterminal: {counts['nonterminal']}; unresolved routes: {counts['unresolvedRoutes']}.",
                f"Recorded status totals: {line}.",
                f"Source revision: {proof['sourceHead'] or 'unknown'}.",
                "Freshness: pinned source snapshot. Chief source reconciliation remains open; this isn't a latest-state claim.",
                "Full private brief saved and protected readback passed. No queue change or provider call.",
                f"Receipt SHA256: {_digest(raw)}",
            ]
        )
        return BriefResult(text, str(receipt_path), _digest(raw), proof["artifactSha256"], proof["sourceQueueRevision"], counts)
