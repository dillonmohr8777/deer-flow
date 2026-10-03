"""Private local Brain Forge build/readback. This CLI has no transport actions."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import uuid
from pathlib import Path

from app.channels.brainforge_project import _json, _pinned
from app.channels.brainforge_workflow import BrainForgeBriefWorkflow


def verify(receipt_path: str, expected_sha256: str, config: dict) -> dict:
    workflow = BrainForgeBriefWorkflow(config)
    receipt = _json({"path": receipt_path, "sha256": expected_sha256})
    if receipt.get("sourceHashes") != workflow.source_hashes or receipt.get("briefSourceHashes") != workflow.module_hashes:
        raise ValueError("receipt source binding does not match configured sources")
    manifest = _json({"path": receipt["manifestPath"], "sha256": receipt["manifestSha256"]})
    job_dir = Path(receipt_path).parent
    if not job_dir.is_relative_to(workflow.output):
        raise ValueError("receipt must be within the configured private output")
    for pin in (manifest["snapshot"], manifest["brief"], {"path": receipt["manifestPath"], "sha256": receipt["manifestSha256"]}):
        if Path(pin["path"]).parent != job_dir:
            raise ValueError("receipt artifact escaped private job directory")
        _pinned(pin)
    read = subprocess.run(
        [sys.executable, "-B", "-s", str(workflow.source / "daily_brief.py"), "read", "--manifest", receipt["manifestPath"], "--expected-manifest-sha256", receipt["manifestSha256"]],
        capture_output=True,
        timeout=30,
        check=False,
    )
    if read.returncode or hashlib.sha256(read.stdout).hexdigest() != receipt["artifactSha256"]:
        raise ValueError("protected brief readback failed")
    project = receipt.get("project")
    if project:
        if workflow.project is None or project["controlSha256"] != workflow.project.config["control"]["sha256"] or project["catalogSha256"] != workflow.project.config["catalog"]["sha256"]:
            raise ValueError("project source binding mismatch")
        if Path(project["path"]).parent != job_dir:
            raise ValueError("project artifact escaped private job directory")
        saved = _json(project)
        current = workflow.project.compile(_json(manifest["snapshot"]), client_id=receipt["clientId"])
        if saved != current:
            raise ValueError("project changed since protected build")
    workflow.validate()
    return {"status": "verified_private_readback", "receiptSha256": expected_sha256, "projectVerified": project is not None, "slackDeliveryVerified": False, "runtimeExecuted": False}


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in {"prepare", "check"}:
        from app.channels.brainforge_setup import main as setup_main

        raise SystemExit(setup_main(argv))
    parser = argparse.ArgumentParser(description=__doc__, epilog="Offline configuration: prepare --help or check --help. These subcommands use their own options and do not require --config.")
    parser.add_argument("command", choices=("prepare", "check", "preflight", "build", "verify"))
    parser.add_argument("--config", required=True)
    parser.add_argument("--client-id", default="__owner__")
    parser.add_argument("--receipt")
    parser.add_argument("--expected-sha256")
    args = parser.parse_args(argv)
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    if args.command == "verify":
        if not args.receipt or not args.expected_sha256:
            parser.error("verify requires --receipt and --expected-sha256")
        result = verify(args.receipt, args.expected_sha256, config)
    else:
        workflow = BrainForgeBriefWorkflow(config)
        if args.command == "preflight":
            result = {"status": "local_source_pins_valid", "projectConfigured": workflow.project is not None, "sourceAccepted": False, "runtimeExecuted": False}
        else:
            job_key = "local-owner-preview:" + str(uuid.uuid4())
            built = workflow.run(job_key=job_key, client_id=args.client_id, thread_sha256=hashlib.sha256(job_key.encode()).hexdigest())
            result = {
                "status": "prepared_private_project",
                "origin": "local owner preview; no Slack trigger",
                "receiptPath": built.receipt_path,
                "receiptSha256": built.receipt_sha256,
                "counts": built.counts,
                "slackDeliveryVerified": False,
                "runtimeExecuted": False,
            }
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
