"""Score local enterprise evidence; never execute receipt commands or call providers."""

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

ARTIFACTS = (
    "fleet/manifest.json",
    "fleet/evals/role-evals.json",
    "docker/docker-compose.yaml",
    "docker/docker-compose-dev.yaml",
    "deploy/helm/deer-flow/Chart.yaml",
    "plans/momentum-enterprise-runtime-contract.md",
)
GROUPS = ("docker", "helm", "tests")
CONFIG = {"version": 1, "artifacts": ARTIFACTS, "receipt_groups": GROUPS, "weight_per_check": 1, "clock": "supplied receipt timestamps only", "random_seed": None}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _reject_constant(value: str) -> None:
    raise ValueError(f"Non-JSON numeric constant: {value}")


def _unique_object(pairs: list[tuple]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object key")
        result[key] = value
    return result


def _json(data: bytes):
    return json.loads(data.decode("utf-8-sig"), parse_constant=_reject_constant, object_pairs_hook=_unique_object)


def _receipt(data: bytes) -> dict:
    receipt = _json(data)
    if not isinstance(receipt, dict):
        raise ValueError("Receipt must be an object")
    for field in ("name", "command", "timestamp_utc"):
        if not isinstance(receipt.get(field), str) or not receipt[field].strip():
            raise ValueError(f"Receipt requires a nonempty {field}")
    status, code = receipt.get("status"), receipt.get("exit_code")
    if status not in ("pass", "fail", "skip") or "exit_code" not in receipt or (code is not None and type(code) is not int):
        raise ValueError("Receipt requires status pass|fail|skip and integer|null exit_code")
    if (status == "pass" and code != 0) or (status == "fail" and (code is None or code == 0)) or (status == "skip" and code is not None):
        raise ValueError("Receipt status contradicts exit_code")
    if datetime.fromisoformat(receipt["timestamp_utc"]).utcoffset() != timedelta(0):
        raise ValueError("timestamp_utc must include UTC timezone Z or +00:00")
    # Raw details may contain logs; preserve their input hash without echoing them.
    return {key: receipt[key] for key in ("name", "command", "status", "exit_code", "timestamp_utc")}


def _git(root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8", timeout=10, check=False)
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def evaluate(root: Path, receipt_paths: list[Path]) -> dict:
    root = root.resolve()
    if not root.is_dir():
        raise ValueError("Repository root must be an existing directory")
    checks, artifacts = [], {}
    for name in ARTIFACTS:
        try:
            path = (root / name).resolve()
            if not path.is_relative_to(root):
                raise ValueError("Artifact resolves outside repository")
            data = path.read_bytes()
            if not data:
                raise ValueError("Artifact is empty")
            artifacts[name] = _sha256(data)
            checks.append({"id": f"artifact:{name}", "status": "pass", "sha256": artifacts[name]})
        except (OSError, ValueError) as error:
            checks.append({"id": f"artifact:{name}", "status": "fail", "reason": str(error)})
            data = None
        if name.endswith(".json"):
            try:
                if data is None:
                    raise ValueError("Artifact is unavailable")
                _json(data)
                checks.append({"id": f"json:{name}", "status": "pass"})
            except (ValueError, UnicodeError) as error:
                checks.append({"id": f"json:{name}", "status": "fail", "reason": str(error)})

    receipts, errors, seen = [], [], set()
    for path in sorted((path.resolve() for path in receipt_paths), key=str):
        try:
            data = path.read_bytes()
            receipt = _receipt(data)
            if receipt["name"] in seen:
                raise ValueError("Duplicate receipt name; provide one final receipt per check")
            seen.add(receipt["name"])
            receipts.append({**receipt, "path": str(path), "sha256": _sha256(data)})
        except (OSError, ValueError, UnicodeError) as error:
            errors.append({"path": str(path), "error": str(error)})
    receipts.sort(key=lambda receipt: receipt["name"])
    for group in GROUPS:
        members = [receipt for receipt in receipts if receipt["name"].partition(".")[0] == group]
        if errors or any(receipt["status"] == "fail" for receipt in members):
            status = "fail"
        elif not members or any(receipt["status"] == "skip" for receipt in members):
            status = "skip"
        else:
            status = "pass"
        checks.append({"id": f"receipts:{group}", "status": status, "names": [receipt["name"] for receipt in members]})

    failed = errors or any(item["status"] == "fail" for item in checks + receipts)
    passed = sum(check["status"] == "pass" for check in checks)
    git_status = _git(root, "status", "--porcelain", "--untracked-files=normal")
    return {
        "benchmark": "enterprise-fleet-evidence-v1",
        "scope": "Local evidence completeness only; not a SWE-bench or Terminal-Bench model score, deployment approval, or proof of production readiness.",
        "status": "fail" if failed else "pass" if passed == len(checks) else "incomplete",
        "score": {"passed": passed, "total": len(checks), "percent": round(100 * passed / len(checks), 2)},
        "checks": checks,
        "receipts": receipts,
        "receipt_errors": errors,
        "provenance": {
            "git_revision": _git(root, "rev-parse", "HEAD"),
            "working_tree_dirty": None if git_status is None else bool(git_status),
            "evaluator_sha256": _sha256(Path(__file__).read_bytes()),
            "config": CONFIG,
            "config_sha256": _sha256(json.dumps(CONFIG, sort_keys=True, separators=(",", ":")).encode("utf-8")),
            "artifact_sha256": artifacts,
            "manifest_sha256": artifacts.get("fleet/manifest.json"),
            "external_datasets": [],
            "prompts": [],
            "model": None,
            "inference_parameters": None,
        },
        "limitations": [
            "Receipt commands are operator assertions; they are never executed or independently authenticated here.",
            "Receipt groups check only supplied receipts and do not establish test coverage, freshness, or deployment behavior.",
            "Artifact hashes cover the listed artifacts only; git revision plus dirty flag does not identify all uncommitted production code.",
            "JSON syntax checks do not validate fleet semantics; ingest the existing fleet test receipt for that evidence.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[4], help="Repository root")
    parser.add_argument("--receipt", type=Path, action="append", default=[], help="Local receipt JSON; repeat for each check")
    parser.add_argument("--output", type=Path, help="New output file; default stdout; existing files are never overwritten")
    args = parser.parse_args()
    try:
        result = evaluate(args.root, args.receipt)
        output = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
        if args.output:
            with args.output.open("x", encoding="utf-8") as handle:
                handle.write(output)
        else:
            print(output, end="")
    except (OSError, ValueError) as error:
        parser.error(str(error))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
