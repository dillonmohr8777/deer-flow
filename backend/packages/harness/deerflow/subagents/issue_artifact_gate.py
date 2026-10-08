"""Fail-closed disposition for a private issue-to-artifact work order.

This is an offline operations gate, not a verifier of factual correctness or
authority to publish. Callers must obtain the work order and receipts from
trusted storage; model-authored JSON alone cannot establish provenance.
Ordinary durable-batch execution status remains unchanged.
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_EMPTY_RESULTS = {"", "no response generated", "none", "null"}


def _value(record: Mapping[str, Any] | None, key: str) -> str:
    value = record.get(key) if isinstance(record, Mapping) else None
    return value.strip() if isinstance(value, str) else ""


def _sources(record: Mapping[str, Any] | None) -> tuple[tuple[str, str, str], ...] | None:
    rows = record.get("source_snapshots") if isinstance(record, Mapping) else None
    if not isinstance(rows, list) or not rows:
        return None
    found: list[tuple[str, str, str]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            return None
        source_id = _value(row, "source_id")
        digest = _value(row, "sha256")
        captured_at = _value(row, "captured_at")
        if not source_id or not _SHA256.fullmatch(digest) or not captured_at:
            return None
        found.append((source_id, digest, captured_at))
    if len(found) != len({row[0] for row in found}):
        return None
    return tuple(sorted(found))


def evaluate_issue_artifact(
    work_order: Mapping[str, Any] | None,
    execution: Mapping[str, Any],
    artifact_receipt: Mapping[str, Any] | None = None,
    review_receipt: Mapping[str, Any] | None = None,
    review_execution: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return an evidence disposition without changing execution status.

    A positive disposition means only that a reviewed artifact is ready for
    its named human owner. It never means that a live client system was fixed.
    """

    missing: list[str] = []
    rework: list[str] = []
    order = work_order if isinstance(work_order, Mapping) else {}
    artifact = artifact_receipt if isinstance(artifact_receipt, Mapping) else {}
    review = review_receipt if isinstance(review_receipt, Mapping) else {}
    reviewer_item = review_execution if isinstance(review_execution, Mapping) else {}
    execution_succeeded = execution.get("status") == "succeeded"

    if not execution_succeeded:
        rework.append("execution_not_succeeded")
    result = execution.get("result")
    if not isinstance(result, str) or result.strip().casefold().rstrip(".!").strip() in _EMPTY_RESULTS:
        rework.append("result_empty_or_sentinel")
    if execution.get("result_truncated") is not False:
        rework.append("result_truncated_or_unknown")

    order_id = _value(order, "work_order_id")
    client_id = _value(order, "canonical_client_id")
    issue_id = _value(order, "issue_id")
    owner_id = _value(order, "decision_owner_id")
    review_item_key = _value(order, "review_item_key")
    sources = _sources(order)
    if not order_id or not client_id or not issue_id or not owner_id or not review_item_key or sources is None:
        missing.append("canonical_work_order_incomplete")
    if order_id and _value(execution, "item_key") != order_id:
        rework.append("execution_work_order_mismatch")

    criteria = order.get("acceptance_criteria")
    executed_criteria = execution.get("acceptance_criteria")
    if not isinstance(criteria, list) or not criteria or not all(isinstance(x, str) and x.strip() for x in criteria):
        missing.append("work_order_acceptance_missing")
    elif executed_criteria != criteria:
        rework.append("delegated_acceptance_mismatch")
    verdict = execution.get("acceptance_verdict")
    if not isinstance(verdict, Mapping):
        missing.append("acceptance_unchecked")
    elif (
        verdict.get("source") != "acceptance_checklist"
        or verdict.get("requirement") != "delegation_acceptance_criteria"
        or verdict.get("all_hold") is not True
        or not isinstance(verdict.get("leaves"), list)
        or not verdict["leaves"]
        or not isinstance(criteria, list)
        or len(verdict["leaves"]) != len(criteria)
        or any(
            not isinstance(leaf, Mapping) or leaf.get("checked") is not True or leaf.get("holds") is not True
            for leaf in verdict["leaves"]
        )
        or any(leaf.get("criterion") != criterion for leaf, criterion in zip(verdict["leaves"], criteria))
        or verdict.get("unchecked") != []
    ):
        rework.append("acceptance_not_held")

    artifact_path = _value(order, "expected_artifact_path")
    artifact_sha = _value(artifact, "sha256")
    readback_sha = _value(artifact, "readback_sha256")
    if (
        not artifact_path
        or not Path(artifact_path).is_absolute()
        or not _value(artifact, "path")
        or not artifact_sha
        or not readback_sha
    ):
        missing.append("artifact_readback_missing")
    elif (
        _value(artifact, "path") != artifact_path
        or not _SHA256.fullmatch(artifact_sha)
        or artifact_sha != readback_sha
        or isinstance(artifact.get("readback_bytes"), bool)
        or not isinstance(artifact.get("readback_bytes"), int)
        or artifact["readback_bytes"] <= 0
    ):
        rework.append("artifact_readback_mismatch")
    if order_id and artifact and _value(artifact, "work_order_id") != order_id:
        rework.append("artifact_work_order_mismatch")
    if artifact and _value(execution, "id") and _value(artifact, "maker_batch_item_id") != _value(execution, "id"):
        rework.append("artifact_maker_mismatch")
    if client_id and issue_id and artifact:
        if _value(artifact, "canonical_client_id") != client_id or _value(artifact, "issue_id") != issue_id:
            rework.append("artifact_identity_mismatch")
    if sources is not None and artifact and _sources(artifact) != sources:
        rework.append("artifact_source_mismatch")

    maker_batch_item = _value(execution, "id")
    maker_actor = _value(artifact, "maker_actor_id")
    reviewer_batch_item = _value(reviewer_item, "id")
    reviewer_actor = _value(review, "reviewer_actor_id")
    if (
        not maker_batch_item.startswith("batch-item-")
        or not maker_actor
        or _value(artifact, "maker_batch_item_id") != maker_batch_item
    ):
        missing.append("maker_provenance_missing")
    if (
        not reviewer_batch_item.startswith("batch-item-")
        or not reviewer_actor
        or not _value(review, "review_id")
        or _value(review, "review_batch_item_id") != reviewer_batch_item
        or reviewer_item.get("status") != "succeeded"
        or reviewer_item.get("result_truncated") is not False
        or not isinstance(reviewer_item.get("result"), str)
        or reviewer_item["result"].strip().casefold().rstrip(".!").strip() in _EMPTY_RESULTS
        or (review_item_key and _value(reviewer_item, "item_key") != review_item_key)
    ):
        missing.append("independent_review_missing")
    elif reviewer_batch_item == maker_batch_item or reviewer_actor == maker_actor:
        rework.append("review_not_independent")
    if review:
        if _value(review, "decision") != "accepted":
            rework.append("review_not_accepted")
        if order_id and _value(review, "work_order_id") != order_id:
            rework.append("review_work_order_mismatch")
        if artifact_sha and _value(review, "artifact_sha256") != artifact_sha:
            rework.append("review_artifact_mismatch")
        if sources is not None and _sources(review) != sources:
            rework.append("review_source_mismatch")

    disposition = "rework" if rework else "needs-evidence" if missing else "ready-for-owner"
    return {
        "work_order_id": order_id or _value(execution, "item_key"),
        "canonical_client_id": client_id or None,
        "issue_id": issue_id or None,
        "execution_status": execution.get("status"),
        "execution_succeeded": execution_succeeded,
        "review_execution_status": reviewer_item.get("status"),
        "disposition": disposition,
        "missing": sorted(set(missing)),
        "rework": sorted(set(rework)),
        "artifact_sha256": artifact_sha or None,
        "review_id": _value(review, "review_id") or None,
        "limitation": "Mechanical evidence gate only; ready-for-owner is not a live fix or publication approval.",
    }


def _read_index(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be a JSON object keyed by item_key")
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description="Classify saved private batch items by artifact evidence")
    parser.add_argument("--batch-export", required=True, type=Path)
    parser.add_argument("--work-orders", type=Path)
    parser.add_argument("--artifact-receipts", type=Path)
    parser.add_argument("--review-receipts", type=Path)
    parser.add_argument("--review-executions", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    orders = _read_index(args.work_orders)
    artifacts = _read_index(args.artifact_receipts)
    reviews = _read_index(args.review_receipts)
    reviewer_items = _read_index(args.review_executions)
    rows: list[dict[str, Any]] = []
    for line in args.batch_export.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        execution = json.loads(line)
        if not isinstance(execution, dict):
            raise ValueError("Batch export must contain JSON objects")
        key = _value(execution, "item_key")
        if not key:
            raise ValueError("Batch item missing item_key")
        rows.append(
            evaluate_issue_artifact(
                orders.get(key), execution, artifacts.get(key), reviews.get(key), reviewer_items.get(key)
            )
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    inputs = (args.batch_export, args.work_orders, args.artifact_receipts, args.review_receipts, args.review_executions)
    if any(path is not None and args.output.resolve() == path.resolve() for path in inputs):
        raise ValueError("Output path must not alias an input")
    with args.output.open("x", encoding="utf-8") as stream:
        stream.writelines(json.dumps(row, sort_keys=True) + "\n" for row in rows)


if __name__ == "__main__":
    main()
