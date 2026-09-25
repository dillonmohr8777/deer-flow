import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";

import {
  DispatchBoard,
  groupRuns,
  laneOf,
  stampDate,
} from "@/components/workspace/command-center/dispatch-board";
import type { ConsoleRunItem } from "@/core/console";

rs.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...rest
  }: {
    href: string;
    children: ReactNode;
  }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

rs.mock("@/components/workspace/command-center/appearance-provider", () => ({
  useWorkspaceAppearance: () => ({ motionOn: false }),
}));

function run(overrides: Partial<ConsoleRunItem>): ConsoleRunItem {
  return {
    run_id: "run-1",
    thread_id: "thread-1",
    thread_title: "Omega lead review",
    assistant_id: "dillon-brain",
    status: "running",
    model_name: "claude-sonnet",
    created_at: "2026-09-24T13:57:00Z",
    updated_at: "2026-09-24T14:05:00Z",
    duration_seconds: 42,
    total_tokens: 100,
    message_count: 2,
    cost: null,
    error: null,
    ...overrides,
  };
}

const RUNS = [
  run({ run_id: "a", status: "running", thread_title: "Working slip" }),
  run({ run_id: "b", status: "pending", thread_title: "Queued slip" }),
  run({ run_id: "c", status: "success", thread_title: "Done slip" }),
  run({ run_id: "d", status: "error", thread_title: "Failed slip" }),
  run({ run_id: "e", status: "timeout", thread_title: "Slow slip" }),
];

function board(props: Partial<Parameters<typeof DispatchBoard>[0]> = {}) {
  const onOpen = rs.fn();
  const onShowAll = rs.fn();
  const onRetry = rs.fn();
  render(
    <DispatchBoard
      runs={RUNS}
      loading={false}
      error={null}
      onRetry={onRetry}
      onOpen={onOpen}
      selectedRunId={null}
      agentLabel={(id) => (id === "dillon-brain" ? "Dillon Brain" : "Agent")}
      startPath="/workspace/chats/new"
      onShowAll={onShowAll}
      hasMore={false}
      {...props}
    />,
  );
  return { onOpen, onShowAll, onRetry };
}

const slip = (title: string) =>
  screen.getByRole("button", { name: new RegExp(title) });

afterEach(() => cleanup());

describe("dispatch board filing", () => {
  it("files each status into the lane that matches what happened", () => {
    expect(laneOf("running")).toBe("desk");
    expect(laneOf("pending")).toBe("desk");
    expect(laneOf("success")).toBe("stamped");
    expect(laneOf("error")).toBe("returned");
    expect(laneOf("timeout")).toBe("returned");
    expect(laneOf("interrupted")).toBe("returned");
    // Unknown statuses never borrow a lane that claims more than was said.
    expect(laneOf("mystery")).toBe("unsorted");
    const groups = groupRuns(RUNS);
    expect(groups.desk).toHaveLength(2);
    expect(groups.stamped).toHaveLength(1);
    expect(groups.returned).toHaveLength(2);
    expect(groups.unsorted).toHaveLength(0);
  });

  it("dates a stamp, and says so when the date was not recorded", () => {
    expect(stampDate("2026-09-24T14:05:00Z")).toMatch(/Sep 2[45]/);
    expect(stampDate(null)).toBeNull();
    expect(stampDate("not a date")).toBeNull();
  });
});

describe("DispatchBoard", () => {
  it("pins only the slip that is actually working", () => {
    board();
    // classList, not a substring: a glued class name must not pass as a pin.
    expect(slip("Working slip").classList.contains("pinned")).toBe(true);
    expect(slip("Working slip").classList.length).toBe(2);
    expect(slip("Queued slip").classList.contains("pinned")).toBe(false);
    expect(slip("Done slip").classList.contains("pinned")).toBe(false);
    expect(slip("Failed slip").classList.contains("pinned")).toBe(false);
    expect(slip("Working slip").textContent).toContain("Working");
    expect(slip("Queued slip").textContent).toContain("Queued");
  });

  it("stamps finished work with its date and returns failures with the reason", () => {
    board();
    const stamp = slip("Done slip").querySelector('[data-testid="ink-stamp"]');
    expect(stamp?.textContent).toMatch(/Done\s*Sep 2[45]/);
    expect(slip("Failed slip").textContent).toContain("Failed");
    expect(slip("Slow slip").textContent).toContain("Timed out");
    expect(
      slip("Failed slip").querySelector('[data-testid="ink-stamp"]'),
    ).toBeNull();
  });

  it("names the agent in words, never the raw id", () => {
    board();
    expect(slip("Working slip").textContent).toContain("Dillon Brain");
    expect(document.body.textContent).not.toContain("dillon-brain");
  });

  it("shows an Unsorted lane only when a status fits no lane", () => {
    board();
    expect(screen.queryByRole("heading", { name: /Unsorted/ })).toBeNull();
    cleanup();
    board({
      runs: [
        ...RUNS,
        run({ run_id: "z", status: "mystery", thread_title: "Odd slip" }),
      ],
    });
    expect(screen.getByRole("heading", { name: /Unsorted/ })).toBeDefined();
    expect(slip("Odd slip").textContent).toContain("mystery");
  });

  it("opens the receipt for a slip and sends 'all runs' to Jobs", () => {
    const { onOpen, onShowAll } = board({ selectedRunId: "c" });
    expect(slip("Done slip").getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(slip("Failed slip"));
    expect(onOpen).toHaveBeenCalledWith(
      expect.objectContaining({ run_id: "d" }),
    );
    fireEvent.click(screen.getByRole("button", { name: /All runs in Jobs/ }));
    expect(onShowAll).toHaveBeenCalled();
  });

  it("says when older work is not on the board", () => {
    board({ hasMore: true });
    expect(
      screen.getByText(/latest 5 runs\. Older work is in Jobs/),
    ).toBeDefined();
  });

  it("uses the shared loading, error and empty states", () => {
    board({ loading: true, runs: undefined });
    expect(screen.getByRole("status").textContent).toContain(
      "Loading the dispatch board",
    );
    cleanup();
    const { onRetry } = board({ error: "Gateway timed out" });
    expect(screen.getByRole("alert").textContent).toContain(
      "Gateway timed out",
    );
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalled();
    cleanup();
    board({ runs: [] });
    expect(screen.getByText("No missions yet")).toBeDefined();
    expect(screen.getByRole("link", { name: /Start a mission/ })).toBeDefined();
  });
});
