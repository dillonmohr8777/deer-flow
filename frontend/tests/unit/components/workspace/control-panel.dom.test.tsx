import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import type { ReactNode } from "react";

import { ControlPanelBody } from "@/components/workspace/control-panel/control-panel";
import {
  buildChatPromptHref,
  CREATE_SOMETHING_CARDS,
  parsePrefillPrompt,
} from "@/components/workspace/control-panel/control-panel-data";
import { AuthProvider } from "@/core/auth/AuthProvider";
import type { User } from "@/core/auth/types";

const workspaceState = rs.hoisted(() => ({
  active_workspace_id: "ws-amp",
  isLoading: false,
  workspaces: [
    { id: "ws-amp", name: "AI Marketing Philly", role: "owner" },
    { id: "ws-1", name: "Sandbox Workspace", role: "member" },
  ],
}));

rs.mock("next/navigation", () => ({
  useRouter: () => ({ push: rs.fn(), replace: rs.fn(), refresh: rs.fn() }),
  usePathname: () => "/workspace/control-panel",
  useSearchParams: () => new URLSearchParams(),
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

rs.mock("@/core/agents/hooks", () => ({
  useAgents: () => ({
    agents: [{ name: "sandbox-agent", builtin: false }],
    isLoading: false,
  }),
}));

rs.mock("@/core/workspaces/hooks", () => ({
  useWorkspaceSelection: () => ({
    data: workspaceState.isLoading
      ? undefined
      : {
          active_workspace_id: workspaceState.active_workspace_id,
          workspaces: workspaceState.workspaces,
        },
    isLoading: workspaceState.isLoading,
    busy: false,
    error: null,
    selectWorkspace: rs.fn(),
  }),
}));

type MockFetchResponse = {
  ok: boolean;
  status: number;
  json: () => Promise<unknown>;
};

const mockApiFetch = rs.hoisted(() =>
  rs.fn(
    async (url: string, _init?: RequestInit): Promise<MockFetchResponse> => {
      if (url.includes("/api/client-portal/clients")) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            workspace_id: workspaceState.active_workspace_id,
            clients: [],
          }),
        };
      }
      return {
        ok: true,
        status: 200,
        json: async () => ({ threads: [], has_more: false }),
      };
    },
  ),
);

rs.mock("@/core/api/fetcher", () => ({
  fetch: mockApiFetch,
  redirectOnUnauthorized: rs.fn(),
  setLoggingOut: rs.fn(),
}));

function renderControlPanel(role: User["system_role"] = "client") {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider
        initialUser={
          { id: "u-cp", email: "fixture-owner", system_role: role } as User
        }
      >
        <ControlPanelBody />
      </AuthProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  workspaceState.active_workspace_id = "ws-amp";
  workspaceState.isLoading = false;
  window.localStorage.clear();
  mockApiFetch.mockClear();
  mockApiFetch.mockImplementation(async (url: string) => {
    if (url.includes("/api/client-portal/clients")) {
      return {
        ok: true,
        status: 200,
        json: async () => ({
          workspace_id: workspaceState.active_workspace_id,
          clients: [],
        }),
      };
    }
    return {
      ok: true,
      status: 200,
      json: async () => ({ threads: [], has_more: false }),
    };
  });
});

afterEach(cleanup);

describe("Client Control Panel", () => {
  it("renders the AI Marketing Philly workspace header, summary strip, Start Here shortcut, and all 6 Create Something cards", () => {
    renderControlPanel("client");

    expect(screen.getByRole("heading", { name: "Control Panel" })).toBeTruthy();
    expect(screen.getByText("AI Marketing Philly")).toBeTruthy();

    const summary = screen.getByTestId("control-panel-summary");
    expect(within(summary).getByText("0 / 5")).toBeTruthy();
    expect(within(summary).getByText("0 / 5 lessons")).toBeTruthy();
    expect(within(summary).getByText("Status unknown")).toBeTruthy();
    expect(within(summary).queryByText(/channels ready/i)).toBeNull();
    expect(within(summary).queryByText(/0 \/ 6 connected/i)).toBeNull();
    const academyLink = within(summary).getByRole("link", {
      name: /Open Start Here \/ Academy/i,
    });
    expect(academyLink.getAttribute("href")).toBe("/workspace/start-here");

    const createGrid = screen.getByTestId("create-something-grid");
    for (const card of CREATE_SOMETHING_CARDS) {
      expect(within(createGrid).getByText(card.title)).toBeTruthy();
    }

    const startLinks = screen.getAllByRole("link", { name: /Start in Chat/i });
    expect(startLinks.length).toBe(6);
    expect(startLinks[0]?.getAttribute("href")).toContain(
      "/workspace/agents/sandbox-agent/chats/new?prompt=",
    );
  });

  it("renders all 4 portal tabs, updates the progress ring, and shows honest empty/readiness states", () => {
    renderControlPanel("client");

    expect(
      screen.getByRole("tab", { name: /Kickoff & Roadmap/i }),
    ).toBeTruthy();
    expect(
      screen.getByRole("tab", { name: /Weekly Plan & Approvals/i }),
    ).toBeTruthy();
    expect(
      screen.getByRole("tab", { name: /Meetings & Action Plans/i }),
    ).toBeTruthy();
    expect(
      screen.getByRole("tab", { name: /Results & Reporting/i }),
    ).toBeTruthy();

    // Check off Day-1 item and verify both checklist counter and ring update
    const firstCheck = screen.getByRole("checkbox", {
      name: "Complete your Business Profile",
    });
    expect(firstCheck.getAttribute("aria-checked")).toBe("false");
    fireEvent.click(firstCheck);
    expect(firstCheck.getAttribute("aria-checked")).toBe("true");
    expect(screen.getByText("1 of 5 done")).toBeTruthy();
    expect(screen.getByText("20%")).toBeTruthy();

    // Switch to Meetings & Action Plans
    const meetingsTab = screen.getByRole("tab", {
      name: /Meetings & Action Plans/i,
    });
    fireEvent.mouseDown(meetingsTab);
    fireEvent.click(meetingsTab);
    expect(
      screen.getByText("Connect Fireflies or upload call notes"),
    ).toBeTruthy();

    // Switch to Results & Reporting (clients get Client Inbox, never staff-only /workspace/reports)
    const reportingTab = screen.getByRole("tab", {
      name: /Results & Reporting/i,
    });
    fireEvent.mouseDown(reportingTab);
    fireEvent.click(reportingTab);
    const reportingPanel = screen.getByRole("tabpanel");
    const clientInboxLink = within(reportingPanel).getByRole("link", {
      name: /Open Client Inbox/i,
    });
    expect(clientInboxLink.getAttribute("href")).toBe("/workspace/inbox");
    expect(
      within(reportingPanel).queryByRole("link", {
        name: /Open Reports & Leads/i,
      }),
    ).toBeNull();

    for (const channel of [
      "Google Ads",
      "GA4",
      "Search Console",
      "Meta Ads",
      "WhatConverts",
      "Buffer",
    ]) {
      expect(screen.getByText(channel)).toBeTruthy();
    }
  });

  it("exposes /workspace/reports shortcut to staff users on Results & Reporting tab", () => {
    renderControlPanel("admin");
    const reportingTab = screen.getByRole("tab", {
      name: /Results & Reporting/i,
    });
    fireEvent.mouseDown(reportingTab);
    fireEvent.click(reportingTab);
    const reportsLink = screen.getByRole("link", {
      name: /Open Reports & Leads/i,
    });
    expect(reportsLink.getAttribute("href")).toBe("/workspace/reports");
  });

  it("builds bounded chat prompt URLs cleanly for clients and staff", () => {
    expect(
      buildChatPromptHref({
        isClient: false,
        agents: [],
        prompt: "Build my page",
      }),
    ).toBe("/workspace/chats/new?prompt=Build%20my%20page");
    expect(
      buildChatPromptHref({
        isClient: true,
        agents: [{ name: "my-agent", builtin: false }],
        prompt: "Hello",
      }),
    ).toBe("/workspace/agents/my-agent/chats/new?prompt=Hello");
    expect(
      buildChatPromptHref({
        isClient: true,
        agents: [],
        agentsLoading: true,
        prompt: "Hello",
      }),
    ).toBe("/workspace/chats/new?prompt=Hello");
    expect(parsePrefillPrompt("   ")).toBeUndefined();
    expect(parsePrefillPrompt("Draft an article")).toBe("Draft an article");
  });

  it("counts and displays running deliverables scoped to the selected workspace header", async () => {
    mockApiFetch.mockImplementation(async (url: string, init?: RequestInit) => {
      const headers = (init?.headers ?? {}) as Record<string, string>;
      expect(headers["X-Portal-Workspace"]).toBe("ws-amp");
      if (url.includes("/api/client-portal/clients")) {
        return {
          ok: true,
          status: 200,
          json: async () => ({ workspace_id: "ws-amp", clients: [] }),
        };
      }
      if (url.includes("state=pending")) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            threads: [
              { id: "t-run", subject: "Homepage refresh", state: "running" },
            ],
            has_more: false,
          }),
        };
      }
      return {
        ok: true,
        status: 200,
        json: async () => ({
          threads: [
            { id: "t-app", subject: "Weekly GBP pack", state: "needs_approval" },
          ],
          has_more: false,
        }),
      };
    });

    renderControlPanel("client");

    const summary = screen.getByTestId("control-panel-summary");
    await waitFor(() => {
      expect(within(summary).getByText("2 active")).toBeTruthy();
    });

    const weeklyTab = screen.getByRole("tab", {
      name: /Weekly Plan & Approvals/i,
    });
    fireEvent.mouseDown(weeklyTab);
    fireEvent.click(weeklyTab);

    expect(screen.getByText("Homepage refresh")).toBeTruthy();
    expect(screen.getByText("Momo is working")).toBeTruthy();
    expect(screen.getByText("Weekly GBP pack")).toBeTruthy();
    expect(screen.getByText("Needs approval")).toBeTruthy();
  });

  it("shows an unavailable error state with Retry instead of None queued when portal requests fail", async () => {
    let fail = true;
    mockApiFetch.mockImplementation(async (url: string) => {
      if (fail) {
        return { ok: false, status: 503, json: async () => ({}) };
      }
      if (url.includes("/api/client-portal/clients")) {
        return {
          ok: true,
          status: 200,
          json: async () => ({ workspace_id: "ws-amp", clients: [] }),
        };
      }
      return {
        ok: true,
        status: 200,
        json: async () => ({ threads: [], has_more: false }),
      };
    });

    renderControlPanel("client");

    const summary = screen.getByTestId("control-panel-summary");
    await waitFor(() => {
      expect(within(summary).getByText("Unavailable")).toBeTruthy();
    });
    expect(within(summary).queryByText("None queued")).toBeNull();

    const weeklyTab = screen.getByRole("tab", {
      name: /Weekly Plan & Approvals/i,
    });
    fireEvent.mouseDown(weeklyTab);
    fireEvent.click(weeklyTab);
    expect(screen.getByTestId("deliverables-error-state")).toBeTruthy();
    expect(
      screen.getByText("Unable to load active deliverables"),
    ).toBeTruthy();

    fail = false;
    fireEvent.click(screen.getByRole("button", { name: /^Retry$/i }));
    await waitFor(() => {
      expect(within(summary).getByText("None queued")).toBeTruthy();
    });
  });

  it("keeps checklist and action-item controls disabled until workspace scope resolves", () => {
    workspaceState.isLoading = true;
    renderControlPanel("client");

    const firstCheck = screen.getByRole("checkbox", {
      name: "Complete your Business Profile",
    });
    expect(firstCheck.hasAttribute("disabled")).toBe(true);
    fireEvent.click(firstCheck);
    expect(window.localStorage.length).toBe(0);
  });
});
