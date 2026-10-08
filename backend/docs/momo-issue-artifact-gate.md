# Private issue-to-artifact gate

This offline classifier separates a durable subagent's execution result from
the outcome Momentum actually needs: a source-backed artifact ready for its
named human owner. It does not change the running Gateway or the general batch
worker. It does not dispatch models, modify client systems, or authorize sends.

From `backend/`, classify an existing owner-scoped JSONL batch export:

```bash
python3 packages/harness/deerflow/subagents/issue_artifact_gate.py \
  --batch-export /absolute/private/batch-results.jsonl \
  --work-orders /absolute/private/work-orders.json \
  --artifact-receipts /absolute/private/artifact-receipts.json \
  --review-receipts /absolute/private/review-receipts.json \
  --review-executions /absolute/private/review-executions.json \
  --output /absolute/private/dispositions.jsonl
```

The four indexes are JSON objects keyed by each maker export row's `item_key`.
Omit an index to classify absent evidence as `needs-evidence`. The output
contains identifiers, evidence gaps and disposition, not full private result
text. A historical `succeeded` row with null `acceptance_verdict` remains
unchecked and cannot become `ready-for-owner`.

Each work order must provide `work_order_id` equal to `item_key`,
`canonical_client_id`, `issue_id`, `decision_owner_id`, `review_item_key`,
`expected_artifact_path`, nonempty `acceptance_criteria`, and nonempty
`source_snapshots` with `source_id`, SHA-256 `sha256`, and `captured_at`.
The batch execution must carry those exact criteria and a checker-produced
`acceptance_verdict` whose leaves were all checked and held.

The artifact receipt must bind the same work order, client, issue, and source
snapshots to the exact path; include its declared `sha256` and a separate coordinator file
readback `readback_sha256` and positive `readback_bytes`. The artifact receipt
also supplies `maker_batch_item_id` equal to the batch export's `id`, and
`maker_actor_id`. The review receipt
must bind `work_order_id`, `artifact_sha256`, the same source snapshots,
`review_id`, `review_batch_item_id` and `reviewer_actor_id`, and
`decision: accepted`. The reviewer must inspect the original sources and
artifact directly. The separate review execution record must be a completed,
nonempty, untruncated batch item matching `review_item_key`; its `id` must
equal the review receipt's `review_batch_item_id`, differ from the maker's
batch item `id`, and use a distinct actor. Both IDs therefore share the
durable batch-item namespace. Store and authorize these receipts outside model-authored
room text; matching JSON strings alone are not an authentication mechanism.
The export command creates a new output file and refuses to overwrite or alias
its inputs.

`ready-for-owner` means only that the artifact passed these mechanical
evidence gates and a separate review was recorded. The human owner still
decides whether the proposed change is correct or may be published. A missing
source, unchecked criterion, empty result, truncated result, missing file
readback, or missing review holds the item. A failed run or conflicting
identity/hash requires rework. Live issue resolution is recorded separately
after authorized application and readback.
