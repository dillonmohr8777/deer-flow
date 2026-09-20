"""Synthetic offline evidence only; this never runs an agent or a deployment."""

import json
from pathlib import Path

from scripts.benchmark.enterprise_fleet.__main__ import ARTIFACTS, evaluate


def test_evidence_score_requires_valid_artifacts_and_passing_receipts(tmp_path: Path) -> None:
    for name in ARTIFACTS:
        artifact = tmp_path / name
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text('{"synthetic": true}' if name.endswith(".json") else "synthetic fixture\n", encoding="utf-8")

    missing = evaluate(tmp_path, [])
    assert missing["score"] == {"passed": 8, "total": 11, "percent": 72.73}
    assert missing["status"] == "incomplete"

    receipts = []
    for group in ("docker", "helm", "tests"):
        receipt = tmp_path / f"{group}.json"
        receipt.write_text(
            json.dumps({"name": f"{group}.synthetic", "command": "synthetic-only", "status": "pass", "exit_code": 0, "timestamp_utc": "2026-09-20T00:00:00Z"}),
            encoding="utf-8",
        )
        receipts.append(receipt)

    passed = evaluate(tmp_path, receipts)
    assert passed["status"] == "pass"
    assert passed["score"] == {"passed": 11, "total": 11, "percent": 100.0}
    assert passed == evaluate(tmp_path, list(reversed(receipts)))
    assert passed["provenance"]["external_datasets"] == []

    test_receipt = json.loads(receipts[-1].read_text(encoding="utf-8"))
    test_receipt.update(status="fail", exit_code=1)
    receipts[-1].write_text(json.dumps(test_receipt), encoding="utf-8")
    assert evaluate(tmp_path, receipts)["score"]["passed"] == 10
    assert evaluate(tmp_path, receipts)["status"] == "fail"

    test_receipt.update(status="skip", exit_code=None)
    receipts[-1].write_text(json.dumps(test_receipt), encoding="utf-8")
    assert evaluate(tmp_path, receipts)["status"] == "incomplete"

    # Contradictory receipts and duplicate names cannot buy passing credit.
    test_receipt.update(status="pass", exit_code=1)
    receipts[-1].write_text(json.dumps(test_receipt), encoding="utf-8")
    assert evaluate(tmp_path, receipts)["receipt_errors"]
    assert evaluate(tmp_path, [receipts[0], receipts[0]])["status"] == "fail"

    manifest = tmp_path / "fleet/manifest.json"
    for invalid in ('{"number": NaN}', '{"id": 1, "id": 2}', "{"):
        manifest.write_text(invalid, encoding="utf-8")
        result = evaluate(tmp_path, [])
        assert result["status"] == "fail"
        assert result["score"]["passed"] == 7
