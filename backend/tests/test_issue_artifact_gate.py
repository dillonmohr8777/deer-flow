"""f40: close self-review and case-sensitivity gaps in the private issue-artifact gate.

`evaluate_issue_artifact` must never return `ready-for-owner` when the
"independent" review is really the maker rerunning itself under the work
order's own key, when the reviewer's own acceptance verdict did not hold, or
when the reviewer's actor id merely differs from the maker's actor id in case.
"""

from copy import deepcopy

from deerflow.subagents.issue_artifact_gate import evaluate_issue_artifact

_SOURCES = [{"source_id": "s1", "sha256": "a" * 64, "captured_at": "2026-01-01T00:00:00Z"}]


def _valid_case() -> dict:
    order = {
        "work_order_id": "wo-1",
        "canonical_client_id": "client-1",
        "issue_id": "issue-1",
        "decision_owner_id": "owner-1",
        "review_item_key": "review-key-1",
        "expected_artifact_path": "/abs/path/artifact.md",
        "acceptance_criteria": ["criterion one", "criterion two"],
        "source_snapshots": _SOURCES,
    }
    criteria = order["acceptance_criteria"]
    execution = {
        "item_key": "wo-1",
        "id": "batch-item-maker-1",
        "status": "succeeded",
        "result": "Did the thing",
        "result_truncated": False,
        "acceptance_criteria": criteria,
        "acceptance_verdict": {
            "source": "acceptance_checklist",
            "requirement": "delegation_acceptance_criteria",
            "all_hold": True,
            "leaves": [{"criterion": c, "checked": True, "holds": True} for c in criteria],
            "unchecked": [],
        },
    }
    artifact = {
        "work_order_id": "wo-1",
        "path": "/abs/path/artifact.md",
        "sha256": "b" * 64,
        "readback_sha256": "b" * 64,
        "readback_bytes": 123,
        "maker_batch_item_id": "batch-item-maker-1",
        "maker_actor_id": "alice",
        "canonical_client_id": "client-1",
        "issue_id": "issue-1",
        "source_snapshots": _SOURCES,
    }
    review = {
        "work_order_id": "wo-1",
        "artifact_sha256": "b" * 64,
        "review_id": "rev-1",
        "review_batch_item_id": "batch-item-reviewer-1",
        "reviewer_actor_id": "bob",
        "decision": "accepted",
        "source_snapshots": _SOURCES,
    }
    review_execution = {
        "id": "batch-item-reviewer-1",
        "item_key": "review-key-1",
        "status": "succeeded",
        "result": "Reviewed and looks good",
        "result_truncated": False,
    }
    return {
        "work_order": order,
        "execution": execution,
        "artifact_receipt": artifact,
        "review_receipt": review,
        "review_execution": review_execution,
    }


def _call(case: dict) -> dict:
    return evaluate_issue_artifact(
        case["work_order"],
        case["execution"],
        case["artifact_receipt"],
        case["review_receipt"],
        case["review_execution"],
    )


def test_valid_case_is_ready_for_owner():
    result = _call(_valid_case())
    assert result["disposition"] == "ready-for-owner"


def test_maker_rerun_as_review_is_not_ready_for_owner():
    case = deepcopy(_valid_case())
    # The work order's own review key is the maker's own work order id: a
    # rerun of the maker satisfies `item_key == review_item_key` trivially,
    # even under a distinct batch item id and a distinct actor.
    case["work_order"]["review_item_key"] = "wo-1"
    case["review_execution"]["item_key"] = "wo-1"
    case["review_execution"]["id"] = "batch-item-maker-rerun"
    case["review_receipt"]["review_batch_item_id"] = "batch-item-maker-rerun"
    case["review_receipt"]["reviewer_actor_id"] = "carol"

    result = _call(case)

    assert result["disposition"] != "ready-for-owner"
    assert "review_not_independent" in result["rework"]


def test_failing_reviewer_verdict_is_not_ready_for_owner():
    case = deepcopy(_valid_case())
    case["review_execution"]["acceptance_verdict"] = {
        "source": "acceptance_checklist",
        "requirement": "delegation_acceptance_criteria",
        "all_hold": False,
        "leaves": [{"criterion": "criterion one", "checked": True, "holds": False}],
        "unchecked": [],
    }

    result = _call(case)

    assert result["disposition"] != "ready-for-owner"
    assert "reviewer_verdict_not_held" in result["rework"]


def test_case_variant_actor_is_not_independent():
    case = deepcopy(_valid_case())
    # Same human, different case: must not read as an independent reviewer.
    case["artifact_receipt"]["maker_actor_id"] = "alice"
    case["review_receipt"]["reviewer_actor_id"] = "Alice"

    result = _call(case)

    assert result["disposition"] != "ready-for-owner"
    assert "review_not_independent" in result["rework"]


def test_reviewer_verdict_as_non_mapping_string_is_not_ready_for_owner():
    case = deepcopy(_valid_case())
    # A string masquerading as a verdict (e.g. a model narrating instead of
    # emitting the checklist shape) must not silently pass as "no verdict".
    case["review_execution"]["acceptance_verdict"] = "all_hold=false"

    result = _call(case)

    assert result["disposition"] != "ready-for-owner"
    assert "reviewer_verdict_not_held" in result["rework"]


def test_reviewer_verdict_partial_mapping_with_empty_leaves_is_not_ready_for_owner():
    case = deepcopy(_valid_case())
    # A Mapping that claims all_hold=True but checked nothing (empty leaves).
    case["review_execution"]["acceptance_verdict"] = {"all_hold": True, "leaves": []}

    result = _call(case)

    assert result["disposition"] != "ready-for-owner"
    assert "reviewer_verdict_not_held" in result["rework"]


def test_fullwidth_actor_variant_is_not_independent():
    case = deepcopy(_valid_case())
    # Same human, fullwidth compatibility variant: NFKC must collapse it.
    case["artifact_receipt"]["maker_actor_id"] = "alice"
    case["review_receipt"]["reviewer_actor_id"] = "ａｌｉｃｅ"  # fullwidth "alice"

    result = _call(case)

    assert result["disposition"] != "ready-for-owner"
    assert "review_not_independent" in result["rework"]


def test_zero_width_spliced_actor_variant_is_not_independent():
    case = deepcopy(_valid_case())
    # Same human, a zero-width joiner spliced into the id: category Cf must
    # be stripped before casefold, not just relied on casefold alone.
    case["artifact_receipt"]["maker_actor_id"] = "alice"
    case["review_receipt"]["reviewer_actor_id"] = "ali​ce"

    result = _call(case)

    assert result["disposition"] != "ready-for-owner"
    assert "review_not_independent" in result["rework"]
