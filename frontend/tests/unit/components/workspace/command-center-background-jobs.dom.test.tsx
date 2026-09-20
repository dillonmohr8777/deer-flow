import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";

import { BackgroundJobs } from "@/components/workspace/command-center/background-jobs";

const mocks = rs.hoisted(() => ({
  stats: { active_runs: 1 },
  statsError: false,
}));

rs.mock("next/link", () => {
  const MockLink = ({
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
  );
  return { default: MockLink };
});

rs.mock("@/core/agents", () => ({
  useAgents: () => ({ agents: [] }),
}));

rs.mock("@/core/console", () => ({
  useConsoleStats: () => ({
    data: mocks.statsError ? undefined : mocks.stats,
    isError: mocks.statsError,
  }),
  useConsoleRuns: (options: { status?: string } = {}) => {
    if (options.status === "running")
      return {
        data: {
          runs: [
            {
              run_id: "r1",
              thread_id: "t1",
              thread_title: "Alpha",
              assistant_id: null,
              status: "running",
              model_name: "model-a",
              total_tokens: 1234,
              error: null,
            },
          ],
          has_more: false,
        },
        isLoading: false,
        isError: false,
      };
    if (options.status === "pending")
      return {
        data: { runs: [], has_more: false },
        isLoading: false,
        isError: false,
      };
    return {
      data: {
        runs: [
          {
            run_id: "r2",
            thread_id: "t2",
            thread_title: "Beta",
            assistant_id: null,
            status: "success",
            model_name: null,
            total_tokens: 50,
            error: null,
          },
          {
            run_id: "r3",
            thread_id: "t3",
            thread_title: null,
            assistant_id: null,
            status: "error",
            model_name: "model-b",
            total_tokens: 7,
            error: "boom excerpt",
          },
          {
            run_id: "r4",
            thread_id: "t4",
            thread_title: "Delta",
            assistant_id: null,
            status: "mystery",
            model_name: null,
            total_tokens: 0,
            error: null,
          },
        ],
        has_more: false,
      },
      isLoading: false,
      isError: false,
    };
  },
}));

afterEach(() => {
  cleanup();
  rs.clearAllMocks();
  mocks.stats = { active_runs: 1 };
  mocks.statsError = false;
});

function open() {
  render(<BackgroundJobs />);
  fireEvent.click(screen.getByRole("button", { name: /background work/i }));
}

describe("BackgroundJobs", () => {
  it("renders real queued/running/terminal/unknown states without invented progress or cost", () => {
    open();
    expect(screen.getByRole("link", { name: "Alpha, Running" })).toBeDefined();
    expect(screen.getByText("No queued jobs right now.")).toBeDefined();
    expect(screen.getByRole("link", { name: "Beta, Completed" })).toBeDefined();
    expect(
      screen.getByRole("link", { name: "Untitled assignment, Failed" }),
    ).toBeDefined();
    expect(
      screen.getByRole("link", { name: "Delta, Status unknown" }),
    ).toBeDefined();
    const body = document.body.textContent ?? "";
    expect(body).toMatch(/Model not recorded/);
    expect(body).toMatch(/1,234/);
    expect(body).toMatch(/boom excerpt/);
    // No fabricated progress bars or cost figures on this surface.
    expect(screen.queryByRole("progressbar")).toBeNull();
    expect(body).not.toMatch(/\$/);
    expect(body).not.toMatch(/%/);
  });

  it("stays hidden when stats are unavailable instead of claiming zero work", () => {
    mocks.statsError = true;
    render(<BackgroundJobs />);
    expect(
      screen.queryByRole("button", { name: /background work/i }),
    ).toBeNull();
  });
});
