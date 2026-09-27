import { describe, expect, it } from "@rstest/core";

import {
  completedSubagentBatchItems,
  isActiveSubagentBatch,
  subagentBatchAcceptanceStatus,
  subagentBatchCriterionStatus,
  subagentBatchProgress,
  subagentBatchWaitingItems,
  type SubagentBatch,
  type SubagentBatchItem,
} from "@/core/subagent-batches/types";

const BATCH: SubagentBatch = {
  id: "batch-1",
  title: "Records",
  subagent_type: "general-purpose",
  status: "running",
  total_items: 10,
  max_live_items: 5,
  max_running_items: 2,
  max_attempts: 3,
  counts: {
    pending: 2,
    queued: 2,
    leased: 1,
    running: 1,
    succeeded: 2,
    failed: 1,
    cancelled: 1,
  },
  created_at: "2026-08-24T00:00:00Z",
  updated_at: "2026-08-24T00:01:00Z",
  completed_at: null,
};

describe("subagent batch progress", () => {
  it("counts only terminal items as completed progress", () => {
    expect(completedSubagentBatchItems(BATCH)).toBe(4);
    expect(subagentBatchProgress(BATCH)).toBe(40);
  });

  it("returns bounded progress for malformed persisted totals or counts", () => {
    expect(subagentBatchProgress({ ...BATCH, total_items: 0 })).toBe(0);
    expect(
      subagentBatchProgress({
        ...BATCH,
        total_items: 1,
        counts: { ...BATCH.counts, succeeded: 10 },
      }),
    ).toBe(100);
  });

  it("separates queued work from items that are starting or running", () => {
    expect(subagentBatchWaitingItems(BATCH)).toBe(4);
  });

  it.each(["queued", "running", "paused"] as const)(
    "treats %s as active",
    (status) => expect(isActiveSubagentBatch({ ...BATCH, status })).toBe(true),
  );

  it.each(["completed", "failed", "cancelled"] as const)(
    "treats %s as terminal",
    (status) => expect(isActiveSubagentBatch({ ...BATCH, status })).toBe(false),
  );
});

const ITEM: SubagentBatchItem = {
  id: "item-1",
  batch_id: "batch-1",
  item_key: "report",
  position: 0,
  status: "succeeded",
  attempt: 1,
  model_name: null,
  result_preview: "Report ready",
  result_truncated: false,
  error: null,
  stop_reason: null,
  token_usage: null,
  acceptance_criteria: ["file:report.txt non-empty", "tests_passed:pnpm test"],
  acceptance_verdict: {
    all_hold: false,
    unchecked: ["tests_passed:pnpm test"],
    leaves: [
      {
        criterion: "file:report.txt non-empty",
        family: "file_non_empty",
        checked: true,
        holds: true,
        detail: "File exists and is non-empty.",
      },
    ],
  },
  started_at: null,
  completed_at: null,
  created_at: "2026-08-24T00:00:00Z",
  updated_at: "2026-08-24T00:01:00Z",
};

describe("subagent batch acceptance status", () => {
  it("keeps execution success separate from incomplete acceptance checks", () => {
    expect(subagentBatchAcceptanceStatus(ITEM)).toBe("needs_review");
    expect(
      subagentBatchCriterionStatus(ITEM, "file:report.txt non-empty"),
    ).toBe("met");
    expect(subagentBatchCriterionStatus(ITEM, "tests_passed:pnpm test")).toBe(
      "needs_review",
    );
  });

  it("labels an objective check that did not hold separately from review", () => {
    const unmet: SubagentBatchItem = {
      ...ITEM,
      acceptance_verdict: {
        all_hold: false,
        unchecked: [],
        leaves: [
          {
            criterion: "file:report.txt non-empty",
            family: "file_non_empty",
            checked: true,
            holds: false,
            detail: "File was empty.",
          },
        ],
      },
    };
    expect(subagentBatchAcceptanceStatus(unmet)).toBe("not_met");
  });

  it("does not imply acceptance when no criteria were supplied", () => {
    expect(
      subagentBatchAcceptanceStatus({ ...ITEM, acceptance_criteria: null }),
    ).toBeNull();
  });
});
