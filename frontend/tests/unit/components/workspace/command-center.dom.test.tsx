import { existsSync } from "node:fs";
import { join } from "node:path";

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
  runs: [] as unknown[],
}));
const contributorRun = {
  run_id: "run-7",
  thread_id: "thread-7",
  thread_title: "Audit the landing page",
  assistant_id: "lead",
  status: "success",
  model_name: "openrouter-muse-spark-contributor",
  created_at: "2026-09-21T01:02:03.000Z",
  updated_at: "2026-09-21T01:03:03.000Z",
  duration_seconds: 42,
  total_tokens: 1234,
  message_count: 4,
  cost: null,
  error: null,
};

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

rs.mock("@/components/workspace/command-center/business-views", () => ({
  ArtifactLibraryView: () => <div data-testid="artifact-library" />,
  ClientSpacesView: () => <div data-testid="client-spaces" />,
  WorkflowsView: () => <div data-testid="workflows" />,
}));

rs.mock("@/core/models/hooks", () => ({
  useModels: () => ({
    models: [
      {
        name: "openrouter-muse-spark-contributor",
        display_name: "Muse Spark 1.3 Contributor (OpenRouter)",
      },
    ],
  }),
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
    data: { runs: mocks.runs, has_more: false },
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
      // The ledger records these IDs doubled; both are one model to a person.
      by_model: {
        "meta/muse-spark-1.3meta/muse-spark-1.3": {
          tokens: 1000,
          runs: 1,
          cost: null,
          input_tokens: 900,
          cache_read_tokens: 0,
        },
        "meta/muse-spark-1.3-contributormeta/muse-spark-1.3-contributor": {
          tokens: 2000,
          runs: 2,
          cost: 0.5,
          input_tokens: 1800,
          cache_read_tokens: 0,
        },
      },
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
  mocks.runs = [];
});

afterEach(() => {
  cleanup();
  rs.clearAllMocks();
});

function metric(label: string) {
  return screen.getByText(label).parentElement!;
}

describe("CommandCenter", () => {
  it("colours the error count for state only: danger, ok, or plain ink", () => {
    mocks.stats = { ...baseStats, total_runs: 0 };
    const first = render(<CommandCenter />);
    expect(metric("Errors & timeouts").dataset.state).toBeUndefined();
    first.unmount();
    mocks.stats = { ...baseStats };
    const second = render(<CommandCenter />);
    expect(metric("Errors & timeouts").dataset.state).toBe("ok");
    second.unmount();
    mocks.stats = { ...baseStats, failed_runs: 2 };
    render(<CommandCenter />);
    expect(metric("Errors & timeouts").dataset.state).toBe("danger");
    // No other numeral carries a state colour.
    expect(metric("Recorded tokens").dataset.state).toBeUndefined();
  });

  it("makes the totals rail a labelled region the keyboard can reach", () => {
    render(<CommandCenter />);
    const rail = screen.getByRole("region", {
      name: "Recorded workspace totals",
    });
    expect(rail.tabIndex).toBe(0);
  });

  it("keeps the brand card and motion switch out of the hero; motion lives in Appearance", () => {
    render(<CommandCenter />);
    expect(screen.queryByRole("switch", { name: "Brand motion" })).toBeNull();
    expect(screen.queryByAltText("Momentum")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Appearance" }));
    expect(screen.getByRole("switch", { name: "Brand motion" })).toBeDefined();
  });

  it("introduces the crew in the hero, lead in front, rather than repeating the lead card", () => {
    const { container } = render(<CommandCenter />);
    const crew = [...container.querySelectorAll("[data-crew]")];
    expect(crew.length).toBeGreaterThanOrEqual(3);
    expect(crew.length).toBeLessThanOrEqual(4);
    for (const el of crew) {
      const slug = el.getAttribute("data-crew");
      if (slug === "dillon-brain") {
        // PaperLayers, not a robot Momo svg. No appearance provider is
        // mounted here, so its motion default (off) holds it to the
        // flattened WebP fallback.
        const img = el.querySelector("img");
        expect(img?.getAttribute("src")).toBe("/momentum/brain/flat.webp");
        expect(
          existsSync(join(process.cwd(), "public", "momentum/brain/flat.webp")),
        ).toBe(true);
        expect(el.closest('[aria-hidden="true"]')).not.toBeNull();
        continue;
      }
      // Canon art by path, and the file is really there: no 404 in the hero.
      const src = el.getAttribute("src") ?? "";
      expect(src).toMatch(/^\/momentum\/momos\/[a-z-]+\.svg$/);
      expect(existsSync(join(process.cwd(), "public", src))).toBe(true);
      // Decoration: the heading beside it says what the page is.
      expect(el.getAttribute("alt")).toBe("");
      expect(el.closest('[aria-hidden="true"]')).not.toBeNull();
    }
    // One lead (Dillon Brain), painted last so it stands in front of the crew.
    const slugs = crew.map((el) => el.getAttribute("data-crew"));
    expect(slugs.filter((slug) => slug === "dillon-brain")).toHaveLength(1);
    expect(slugs.at(-1)).toBe("dillon-brain");
    expect(new Set(slugs).size).toBe(slugs.length);
  });

  it("names models by display name, never the slug or the Contributor tier", () => {
    mocks.runs = [contributorRun];
    render(<CommandCenter />);
    expect(screen.getByText("Muse Spark 1.3")).toBeDefined();
    fireEvent.click(
      screen.getByRole("button", { name: /Audit the landing page/ }),
    );
    expect(screen.getByRole("dialog")).toBeDefined();
    expect(screen.getAllByText("Muse Spark 1.3").length).toBe(2);
    expect(document.body.textContent).not.toMatch(/contributor/i);
    expect(document.body.textContent).not.toContain("openrouter-");
  });

  it("labels the tabs the backend only partly supports as Preview", () => {
    render(<CommandCenter />);
    for (const name of ["Mission Control", "Agent Studio", "Jobs", "Workflows"])
      expect(screen.getByRole("button", { name })).toBeDefined();
    for (const name of [
      "Client Spaces",
      "Business Intelligence",
      "Artifact Library",
    ])
      expect(screen.getByRole("button", { name: `${name} Preview` })).toBeDefined();
    expect(screen.queryByText(/not connected yet/)).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Client Spaces Preview" }));
    expect(screen.getByText(/Client spaces are not connected yet/)).toBeDefined();
    expect(screen.getByTestId("client-spaces")).toBeDefined();
  });

  it("merges usage rows that share a display name", () => {
    render(<CommandCenter />);
    fireEvent.click(
      screen.getByRole("button", { name: /^Business Intelligence/ }),
    );
    const rows = screen.getAllByRole("row", { name: /Muse Spark 1\.3/ });
    expect(rows).toHaveLength(1);
    expect(rows[0]!.textContent).toContain("3,000");
    expect(rows[0]!.textContent).toContain("$0.50");
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
      screen.getByRole("button", { name: /^Business Intelligence/ }),
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
