import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";

import { CommandCenter } from "@/components/workspace/command-center/command-center";

const baseStats = {
  active_runs: 0,
  currency: "USD",
  failed_runs: 0 as number | undefined,
  total_agents: 1,
  total_cost: 0.004,
  total_runs: 1,
  total_threads: 1,
  total_tokens: 30 as number | undefined,
};
const mocks = rs.hoisted(() => ({
  stats: undefined as unknown,
  statsLoading: false,
}));

rs.mock("next/image", () => ({
  default: ({
    alt,
    ...rest
  }: {
    alt: string;
    src: string;
    width: number;
    height: number;
  }) => <img alt={alt} {...rest} />,
}));

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

rs.mock("@/components/ui/sidebar", () => ({
  SidebarTrigger: () => <button aria-label="Open sidebar" />,
}));

rs.mock("@/components/workspace/thread-subagent-batches", () => ({
  ThreadSubagentBatches: () => null,
}));

rs.mock("@/components/workspace/command-center/agent-topology", () => ({
  AgentTopology: () => <div data-testid="agent-topology" />,
}));

rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: () => ({ user: { id: "user-1", permissions: ["runs:read"] } }),
}));

rs.mock("@/core/auth/permissions", () => ({
  PERMISSIONS: { RUNS_CANCEL: "runs:cancel" },
  hasPermission: () => true,
}));

rs.mock("@/core/agents", () => ({
  useAgents: () => ({ agents: [{ name: "lead", display_name: "Lead" }] }),
}));

rs.mock("@/core/subagents", () => ({
  useSubagents: () => ({ subagents: [], isLoading: false, error: null }),
}));

rs.mock("@/core/threads/utils", () => ({
  pathOfThread: (threadId: string) => `/workspace/chats/${threadId}`,
}));

rs.mock("@/core/console", () => ({
  useCancelConsoleRun: () => ({
    isError: false,
    isPending: false,
    mutate: rs.fn(),
    reset: rs.fn(),
  }),
  useConsoleRuns: () => ({
    data: { runs: [], has_more: false },
    error: null,
    isError: false,
    isFetching: false,
    isLoading: false,
    isSuccess: true,
    refetch: rs.fn(),
  }),
  useConsoleStats: () => ({
    data: mocks.stats,
    isError: false,
    isLoading: mocks.statsLoading,
    refetch: rs.fn(),
  }),
  useConsoleUsage: () => ({
    data: {
      by_model: {},
      currency: "USD",
      days: [],
      total_cost: 0.004,
      total_runs: 1,
      total_tokens: 30,
    },
    isError: false,
    isLoading: false,
    refetch: rs.fn(),
  }),
  useConsoleUsageLedger: () => ({
    data: {
      attempts: [
        {
          attempt_status: "error",
          cache_read_tokens: 3,
          caller: "lead",
          created_at: "2026-09-21T01:02:03.000Z",
          error_type: "rate_limit",
          estimated_cost: 0.004,
          estimated_currency: "USD",
          event_id: 99,
          input_tokens: 10,
          latency_ms: 1250,
          llm_call_index: 2,
          organization_id: "org-1",
          output_tokens: 20,
          provider: "openai",
          provider_attempt_id: "attempt-1",
          provider_reported_cost: 0.0123,
          provider_reported_currency: "USD",
          requested_model: "gpt-test",
          resolved_model: "gpt-test",
          run_id: "run-1",
          assistant_id: "lead",
          thread_id: "thread-1",
          total_tokens: 30,
        },
      ],
      has_more: true,
    },
    isError: false,
    isFetching: false,
    isLoading: false,
    refetch: rs.fn(),
  }),
}));

beforeEach(() => {
  mocks.stats = { ...baseStats };
  mocks.statsLoading = false;
});

afterEach(() => {
  cleanup();
  rs.clearAllMocks();
});

function metric(label: string) {
  return screen.getByText(label).parentElement!;
}

describe("CommandCenter", () => {
  it("marks errors as an exception only when failures were recorded", () => {
    const { unmount } = render(<CommandCenter />);
    expect(metric("Errors & timeouts").dataset.exception).toBe("false");
    unmount();
    mocks.stats = { ...baseStats, failed_runs: 2 };
    render(<CommandCenter />);
    expect(metric("Errors & timeouts").dataset.exception).toBe("true");
  });

  it("says loading or unavailable instead of printing a number or a dash", () => {
    mocks.statsLoading = true;
    const { unmount } = render(<CommandCenter />);
    expect(metric("Recorded tokens").textContent).toBe(
      "Recorded tokensLoading",
    );
    unmount();
    mocks.statsLoading = false;
    mocks.stats = { ...baseStats, total_tokens: undefined };
    render(<CommandCenter />);
    expect(metric("Recorded tokens").textContent).toBe(
      "Recorded tokensUnavailable",
    );
    expect(metric("Recorded runs").textContent).toBe("Recorded runs1");
  });

  it("surfaces provider attempt receipts without presenting estimates as invoices", () => {
    render(<CommandCenter />);
    fireEvent.click(
      screen.getByRole("button", { name: "Business Intelligence" }),
    );

    expect(screen.getByText("Provider attempt ledger")).toBeDefined();
    expect(screen.getByText("attempt-1")).toBeDefined();
    expect(screen.getByText("rate_limit")).toBeDefined();
    expect(screen.getByText("openai")).toBeDefined();
    expect(screen.getByRole("cell", { name: /30/ })).toBeDefined();
    expect(screen.getByText("1,250ms")).toBeDefined();
    expect(screen.getAllByText("$0.0123").length).toBeGreaterThan(0);
    expect(
      screen.getByRole("row", { name: /attempt-1/ }).textContent,
    ).toContain("$0.004");
    expect(document.body.textContent).toContain(
      "does not approve, block, or authorize provider spend",
    );
    expect(document.body.textContent).toContain(
      "not your provider balance or invoice",
    );
  });
});
