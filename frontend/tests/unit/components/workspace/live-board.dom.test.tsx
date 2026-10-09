import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, render, screen } from "@testing-library/react";

import { LiveBoard } from "@/components/workspace/command-center/live-board";

afterEach(cleanup);

const q = rs.hoisted(() => ({
  spend: {} as Record<string, unknown>,
  board: {} as Record<string, unknown>,
  approvals: {} as Record<string, unknown>,
  stats: {} as Record<string, unknown>,
  runs: {} as Record<string, unknown>,
}));

rs.mock("@/components/workspace/command-center/appearance-provider", () => ({
  useWorkspaceAppearance: () => ({ motionOn: false }),
}));
rs.mock("@/core/command-center", () => ({
  useSpend: () => q.spend,
  useBoard: () => q.board,
}));
rs.mock("@/core/approvals", () => ({ useApprovals: () => q.approvals }));
rs.mock("@/core/console", () => ({
  useConsoleStats: () => q.stats,
  useConsoleRuns: () => q.runs,
}));

const off = (reason: string) => ({ available: false, reason });

function setAll(overrides: Partial<typeof q> = {}) {
  Object.assign(q, {
    spend: {
      data: {
        enabled: true,
        routes: {
          bulk: {
            model: "m1",
            today_usd: 0.5,
            month_usd: 1.5,
            daily_cap_usd: 1,
            monthly_cap_usd: null,
            priced: true,
            unpriced_usage: false,
          },
        },
      },
      dataUpdatedAt: Date.parse("2026-10-06T14:00:00Z"),
    },
    board: {
      data: {
        as_of: "2026-10-06T14:00:00Z",
        admission: {
          available: true,
          as_of: "2026-10-06T13:00:00Z",
          ceiling_usd: 20,
          used_usd: 1.5,
          by_route: { openrouter: 1.5 },
        },
        evals: {
          available: true,
          as_of: "2026-10-06T10:00:00Z",
          weeks: [{ week: "2026-W41", pass_rate: 0.9, runs: 2, tasks: 50 }],
        },
        lobby: {
          available: true,
          as_of: "2026-10-06T09:55",
          nodes: [{ id: "dex" }, { id: "maya" }],
          edges: [{ source: "dex", target: "maya", score: 4 }],
        },
      },
    },
    approvals: {
      data: [
        { id: "b", title: "Newer", created_at: "2026-10-06T10:00:00Z" },
        { id: "a", title: "Oldest draft", created_at: "2026-10-01T10:00:00Z" },
      ],
      dataUpdatedAt: 1,
    },
    stats: { data: { active_runs: 1 } },
    runs: {
      data: {
        runs: [
          {
            run_id: "r1",
            status: "running",
            assistant_id: "lead",
            thread_title: "Weekly report",
          },
        ],
        has_more: false,
      },
      dataUpdatedAt: 1,
    },
    ...overrides,
  });
}

const renderBoard = (canReadRuns = true) =>
  render(
    <LiveBoard canReadRuns={canReadRuns} agentLabel={(id) => `agent ${id}`} />,
  );

describe("LiveBoard", () => {
  it("shows real values with a source and as-of line on every tile", () => {
    setAll();
    renderBoard();
    expect(screen.getAllByText(/^Source:/)).toHaveLength(6);
    expect(screen.getByText("Oldest draft")).toBeTruthy();
    expect(screen.getByText("2026-W41")).toBeTruthy();
    expect(screen.getByText("90%")).toBeTruthy();
    expect(screen.getByText(/\(no cap set\)/)).toBeTruthy();
    expect(screen.getByText(/agent lead/)).toBeTruthy();
    expect(
      screen.getByRole("img", { name: /2 agents and 1 links/ }),
    ).toBeTruthy();
    expect(screen.queryByText("Unavailable.")).toBeNull();
  });

  it("says unavailable, with the reason, instead of zero", () => {
    setAll({
      spend: {
        isError: true,
        error: new Error("Only a workspace administrator can see this."),
      },
      board: {
        data: {
          as_of: "x",
          admission: off("No ledger."),
          evals: off("Run make agency-evals."),
          lobby: off("Host-only for now."),
        },
      },
      approvals: { isError: true, error: new Error("nope") },
    });
    renderBoard(false);
    expect(screen.getAllByText("Unavailable.").length).toBe(6);
    expect(screen.getByText(/Host-only for now\./)).toBeTruthy();
    expect(screen.getByText(/Run make agency-evals\./)).toBeTruthy();
    expect(screen.getByText(/Your role cannot read runs/)).toBeTruthy();
    expect(screen.queryByText("0")).toBeNull();
  });

  it("labels each tile region for assistive tech", () => {
    setAll();
    renderBoard();
    for (const name of [
      "Spend vs caps",
      "Approvals waiting",
      "Agents active now",
      "Paid-route ledger",
      "Eval pass rate by week",
      "Lobby friendships",
    ])
      expect(screen.getByRole("region", { name })).toBeTruthy();
  });
});
