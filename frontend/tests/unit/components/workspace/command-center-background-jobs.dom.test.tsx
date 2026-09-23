import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";

import { SidebarProvider } from "@/components/ui/sidebar";
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
              model_name: "openrouter-muse-spark-contributor",
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
          {
            run_id: "r5",
            thread_id: "t5",
            thread_title: "Stopped work",
            assistant_id: null,
            status: "interrupted",
            model_name: "model-c",
            total_tokens: 12,
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

function renderDocked(variant?: "sidebar" | "header") {
  return render(
    <SidebarProvider>
      <BackgroundJobs variant={variant} />
    </SidebarProvider>,
  );
}

function open() {
  renderDocked();
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
    expect(
      screen.getByRole("link", { name: "Stopped work, Interrupted" }),
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

  it("shows the model's display name, never the routing slug or tier word", () => {
    open();
    const body = document.body.textContent ?? "";
    expect(body).toMatch(/Muse Spark 1\.3/);
    expect(body).not.toMatch(/openrouter|contributor/i);
  });

  it("says Unavailable when stats fail instead of claiming zero work", () => {
    mocks.statsError = true;
    renderDocked();
    const button = screen.getByRole("button", {
      name: "Background work, count unavailable",
    });
    expect(button.textContent).toContain("Unavailable");
    expect(button.textContent).not.toMatch(/\d/);
  });

  it("docks in the sidebar and the header instead of floating over content", () => {
    const { unmount } = renderDocked();
    const row = screen.getByRole("button", {
      name: "Background work, 1 queued or running jobs",
    });
    expect(row.closest('[data-sidebar="menu-item"]')).not.toBeNull();
    for (let el: Element | null = row; el; el = el.parentElement)
      expect(el.classList.contains("fixed")).toBe(false);
    unmount();

    renderDocked("header");
    const icon = screen.getByRole("button", {
      name: "Background work, 1 queued or running jobs",
    });
    expect(icon.textContent).toBe("1");
    expect(icon.closest('[data-sidebar="menu-item"]')).toBeNull();
  });
});
