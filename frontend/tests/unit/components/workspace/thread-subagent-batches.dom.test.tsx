import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

const featureState = rs.hoisted(() => ({
  repositoryAvailable: true,
  workerRunning: false,
}));
const batchState = rs.hoisted(() => ({
  batches: [] as Array<Record<string, unknown>>,
  control: rs.fn(),
  itemPages: [] as Array<Array<Record<string, unknown>>>,
  fetchNextPage: rs.fn(),
  hasNextPage: false,
}));

rs.mock("@/core/features", () => ({
  useSubagentBatchesCapability: () => ({
    ...featureState,
    maxRunning: 3,
    isLoading: false,
  }),
}));

rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    t: {
      common: { loading: "Loading", loadMore: "Load more" },
      subagentBatches: {
        label: "Missions",
        title: "Missions",
        description: "Durable mission work",
        workerUnavailable:
          "The mission worker isn't running. Existing results remain readable, but work is not progressing and controls are unavailable.",
        empty: "No missions yet",
        emptyHint: "Start a mission",
        loadFailed: "Load failed",
        active: "Active",
        pause: "Pause",
        resume: "Resume",
        cancel: "Cancel",
        retryItem: "Retry",
        exportResults: "Export JSONL",
        viewItems: "View items",
        hideItems: "Hide items",
        itemsFailed: "Mission items failed",
        progress: (completed: number, total: number) =>
          `${completed} of ${total} items finished`,
        liveWindow: (count: number) => `Live window ${count}`,
        runningCapacity: (running: number, maximum: number) =>
          `${running} running · up to ${maximum} at once`,
        waiting: (count: number) => `${count} waiting`,
        starting: (count: number) => `${count} starting`,
        itemStatus: {
          pending: "Pending",
          queued: "Queued",
          leased: "Starting",
          running: "Running",
          succeeded: "Execution finished",
          failed: "Execution failed",
          cancelled: "Cancelled",
        },
        acceptance: {
          heading: "Acceptance checks",
          disclaimer: "Checks cover recorded evidence only.",
          checking: "Checks pending",
          met: "Checks met",
          not_met: "Checks not met",
          needs_review: "Review needed",
          unverified: "Unverified",
        },
        status: {
          queued: "Queued",
          running: "Running",
          paused: "Paused",
          completed: "Completed",
          failed: "Failed",
          cancelled: "Cancelled",
        },
      },
    },
  }),
}));

rs.mock("@/core/subagent-batches", () => ({
  completedSubagentBatchItems: () => 1,
  isActiveSubagentBatch: (batch: { status: string }) =>
    ["queued", "running", "paused"].includes(batch.status),
  subagentBatchAcceptanceStatus: (item: {
    acceptance_criteria?: string[] | null;
    acceptance_verdict?: {
      all_hold: boolean;
      leaves: Array<{ checked: boolean; holds: boolean }>;
    } | null;
    status: string;
  }) => {
    if (!item.acceptance_criteria?.length) return null;
    if (!item.acceptance_verdict) {
      return ["pending", "queued", "leased", "running"].includes(item.status)
        ? "checking"
        : "unverified";
    }
    if (item.acceptance_verdict.all_hold) return "met";
    return item.acceptance_verdict.leaves.some(
      (leaf) => leaf.checked && !leaf.holds,
    )
      ? "not_met"
      : "needs_review";
  },
  subagentBatchCriterionStatus: (
    item: {
      acceptance_verdict?: {
        leaves: Array<{
          criterion: string;
          checked: boolean;
          holds: boolean;
        }>;
      } | null;
      status: string;
    },
    criterion: string,
  ) => {
    if (!item.acceptance_verdict) {
      return ["pending", "queued", "leased", "running"].includes(item.status)
        ? "checking"
        : "unverified";
    }
    const leaf = item.acceptance_verdict.leaves.find(
      (candidate) => candidate.criterion === criterion,
    );
    if (!leaf || !leaf.checked) return "needs_review";
    return leaf.holds ? "met" : "not_met";
  },
  subagentBatchProgress: () => 50,
  subagentBatchWaitingItems: (batch: {
    counts: { pending: number; queued: number };
  }) => batch.counts.pending + batch.counts.queued,
  subagentBatchResultsUrl: () => "/results.jsonl",
  useControlSubagentBatch: () => ({
    isPending: false,
    variables: undefined,
    mutate: batchState.control,
  }),
  useRetrySubagentBatchItem: () => ({
    isPending: false,
    variables: undefined,
    mutate: rs.fn(),
  }),
  useSubagentBatchItems: () => ({
    data: { pages: batchState.itemPages },
    isLoading: false,
    isError: false,
    hasNextPage: batchState.hasNextPage,
    isFetchingNextPage: false,
    fetchNextPage: batchState.fetchNextPage,
  }),
  useSubagentBatches: () => ({
    data: batchState.batches,
    isLoading: false,
    isError: false,
  }),
}));

import { ThreadSubagentBatches } from "@/components/workspace/thread-subagent-batches";

const HISTORICAL_BATCH = {
  id: "batch-1",
  title: "Historical records",
  subagent_type: "general-purpose",
  status: "running",
  total_items: 2,
  max_live_items: 2,
  max_running_items: 1,
  max_attempts: 3,
  counts: {
    pending: 0,
    queued: 0,
    leased: 0,
    running: 1,
    succeeded: 1,
    failed: 0,
    cancelled: 0,
  },
  created_at: "2026-08-24T00:00:00Z",
  updated_at: "2026-08-24T00:01:00Z",
  completed_at: null,
};

afterEach(() => {
  cleanup();
  featureState.repositoryAvailable = true;
  featureState.workerRunning = false;
  batchState.batches = [];
  batchState.control.mockReset();
  batchState.itemPages = [];
  batchState.fetchNextPage.mockReset();
  batchState.hasNextPage = false;
});

describe("ThreadSubagentBatches capability gating", () => {
  it("keeps historical batches readable when the worker is stopped", async () => {
    batchState.batches = [HISTORICAL_BATCH];
    render(<ThreadSubagentBatches threadId="thread-1" />);

    fireEvent.click(screen.getByRole("button", { name: /Missions/ }));

    expect(
      await screen.findByText(
        "The mission worker isn't running. Existing results remain readable, but work is not progressing and controls are unavailable.",
      ),
    ).toBeDefined();
    expect(screen.getByRole("button", { name: "Pause" })).toHaveProperty(
      "disabled",
      true,
    );
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveProperty(
      "disabled",
      true,
    );
    expect(
      screen.getByRole("link", { name: "Export JSONL" }).getAttribute("href"),
    ).toBe("/results.jsonl");
  });

  it("hides an unused batch surface when neither worker nor history exists", () => {
    render(<ThreadSubagentBatches threadId="thread-1" />);
    expect(screen.queryByRole("button", { name: "Missions" })).toBeNull();
  });

  it("loads the next page of batch items", async () => {
    batchState.batches = [HISTORICAL_BATCH];
    batchState.itemPages = [
      [
        {
          id: "item-1",
          item_key: "record-1",
          status: "succeeded",
          result_preview: "done",
        },
      ],
    ];
    batchState.hasNextPage = true;
    render(<ThreadSubagentBatches threadId="thread-1" />);

    fireEvent.click(screen.getByRole("button", { name: /Missions/ }));
    fireEvent.click(screen.getByRole("button", { name: "View items" }));
    fireEvent.click(await screen.findByRole("button", { name: "Load more" }));

    expect(batchState.fetchNextPage).toHaveBeenCalledTimes(1);
  });

  it("shows live capacity and queue states without implying simultaneous workers", async () => {
    batchState.batches = [
      {
        ...HISTORICAL_BATCH,
        total_items: 10,
        max_live_items: 7,
        max_running_items: 5,
        counts: {
          pending: 3,
          queued: 4,
          leased: 1,
          running: 2,
          succeeded: 1,
          failed: 0,
          cancelled: 0,
        },
      },
    ];
    render(<ThreadSubagentBatches threadId="thread-1" />);

    fireEvent.click(screen.getByRole("button", { name: /Missions/ }));

    expect(
      await screen.findByText("2 running · up to 5 at once"),
    ).toBeDefined();
    expect(screen.getByText("Live window 7")).toBeDefined();
    expect(screen.getByText("7 waiting")).toBeDefined();
    expect(screen.getByText("1 starting")).toBeDefined();
    expect(screen.getByText("1 of 10 items finished")).toBeDefined();
  });

  it("shows acceptance checks separately from execution status", async () => {
    batchState.batches = [HISTORICAL_BATCH];
    batchState.itemPages = [
      [
        {
          id: "item-1",
          item_key: "record-1",
          status: "succeeded",
          result_preview: "done",
          acceptance_criteria: [
            "file:report.txt non-empty",
            "tests_passed:pnpm test",
          ],
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
        },
      ],
    ];
    render(<ThreadSubagentBatches threadId="thread-1" />);

    fireEvent.click(screen.getByRole("button", { name: /Missions/ }));
    fireEvent.click(screen.getByRole("button", { name: "View items" }));

    expect(await screen.findByText("Execution finished")).toBeDefined();
    expect(screen.getAllByText("Review needed")).toHaveLength(2);
    expect(screen.getByText("Acceptance checks")).toBeDefined();
    expect(screen.getByText("file:report.txt non-empty")).toBeDefined();
    expect(screen.getByText("tests_passed:pnpm test")).toBeDefined();
    expect(
      screen.getByText("Checks cover recorded evidence only."),
    ).toBeDefined();
  });
});
