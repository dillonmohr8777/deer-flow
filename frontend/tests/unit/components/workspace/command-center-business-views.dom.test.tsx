import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";

import {
  ClientSpacesView,
  WorkflowsView,
} from "@/components/workspace/command-center/business-views";
import { I18nProvider } from "@/core/i18n/context";

afterEach(cleanup);

function renderWithI18n(ui: ReactNode) {
  return render(<I18nProvider initialLocale="en-US">{ui}</I18nProvider>);
}

rs.mock("next/link", () => {
  const MockLink = ({
    href,
    children,
  }: {
    href: string;
    children: ReactNode;
  }) => <a href={href}>{children}</a>;
  return { default: MockLink };
});

rs.mock("@/core/scheduled-tasks/hooks", () => ({
  useScheduledTasks: () => ({
    data: [
      {
        id: "task-1",
        title: "",
        schedule_type: null,
        status: "enabled",
        next_run_at: null,
        last_run_at: null,
      },
    ],
    isLoading: false,
    isError: false,
  }),
}));

const clientsMock = rs.hoisted(() => ({
  data: undefined as unknown,
  isLoading: false,
  isError: false,
  refetch: rs.fn(),
}));

rs.mock("@/core/clients", () => ({
  useClients: () => clientsMock,
}));

const fleetMock = rs.hoisted(() => ({
  templates: {
    data: [] as unknown[],
    isLoading: false,
    isError: false,
  },
  agents: {
    data: [] as unknown[],
    isLoading: false,
    isError: false,
  },
  stampMutate: rs.fn(),
  stampIsPending: false,
  stampIsError: false,
  stampError: undefined as unknown,
}));

rs.mock("@/core/fleet", () => ({
  useFleetTemplates: () => fleetMock.templates,
  useClientAgents: () => fleetMock.agents,
  useStampClientAgent: () => ({
    mutate: fleetMock.stampMutate,
    isPending: fleetMock.stampIsPending,
    isError: fleetMock.stampIsError,
    error: fleetMock.stampError,
  }),
}));

describe("WorkflowsView truth labels", () => {
  it("labels unknown schedule fields instead of inventing values", () => {
    renderWithI18n(<WorkflowsView />);
    expect(screen.getByText("Untitled workflow")).toBeTruthy();
    expect(screen.getByText("Schedule not reported")).toBeTruthy();
    expect(screen.getByText("Not scheduled")).toBeTruthy();
    expect(screen.getByText("No runs recorded")).toBeTruthy();
  });
});

describe("ClientSpacesView", () => {
  afterEach(() => {
    clientsMock.data = undefined;
    clientsMock.isLoading = false;
    clientsMock.isError = false;
    fleetMock.templates.data = [];
    fleetMock.templates.isLoading = false;
    fleetMock.agents.data = [];
    fleetMock.agents.isLoading = false;
    fleetMock.stampMutate = rs.fn();
    fleetMock.stampIsPending = false;
    fleetMock.stampIsError = false;
    fleetMock.stampError = undefined;
  });

  it("shows an empty state when no clients exist yet", () => {
    clientsMock.data = [];
    renderWithI18n(<ClientSpacesView />);
    expect(screen.getByText(/No clients yet/)).toBeTruthy();
  });

  it("shows a retry notice on error", () => {
    clientsMock.isError = true;
    renderWithI18n(<ClientSpacesView />);
    expect(screen.getByText("Clients couldn't be loaded.")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Retry/ })).toBeTruthy();
  });

  it("lists each client with status, assigned people, and linked projects", () => {
    clientsMock.data = [
      {
        id: "c1",
        display_name: "Acme",
        status: "active",
        assignments: [
          { user_id: "u1", role: "account_manager" },
          { user_id: "u2", role: "contributor" },
        ],
        project_count: 3,
      },
      {
        id: "c2",
        display_name: "Globex",
        status: "prospect",
        assignments: [],
        project_count: 0,
      },
    ];
    renderWithI18n(<ClientSpacesView />);

    const acmeRow = screen.getByText("Acme").closest("li");
    expect(acmeRow?.textContent).toContain("Active");
    expect(acmeRow?.textContent).toContain("2 assigned");
    expect(acmeRow?.textContent).toContain("3 projects");

    const globexRow = screen.getByText("Globex").closest("li");
    expect(globexRow?.textContent).toContain("Prospect");
    expect(globexRow?.textContent).toContain("0 assigned");
    expect(globexRow?.textContent).toContain("0 projects");
  });

  it("shows 'no agents yet' for a client with none stamped", () => {
    clientsMock.data = [
      {
        id: "c1",
        display_name: "Acme",
        status: "active",
        assignments: [],
        project_count: 0,
      },
    ];
    renderWithI18n(<ClientSpacesView />);
    expect(screen.getByText("No agents yet.")).toBeTruthy();
  });

  it("lists a client's stamped agents", () => {
    clientsMock.data = [
      {
        id: "c1",
        display_name: "Acme",
        status: "active",
        assignments: [],
        project_count: 0,
      },
    ];
    fleetMock.agents.data = [
      {
        client_id: "c1",
        template_id: "weekly-client-report",
        template_version: "1",
        agent_name: "acme-weekly-client-report",
        display_name: null,
        description: "Weekly report",
        scheduled_task_id: "task-1",
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      },
    ];
    renderWithI18n(<ClientSpacesView />);
    expect(screen.getByText("acme-weekly-client-report")).toBeTruthy();
  });

  it("excludes already-stamped templates from the add-from-template menu", () => {
    clientsMock.data = [
      {
        id: "c1",
        display_name: "Acme",
        status: "active",
        assignments: [],
        project_count: 0,
      },
    ];
    fleetMock.templates.data = [
      { id: "weekly-client-report", name: "Weekly Client Report" },
      { id: "review-replies", name: "Review Replies" },
    ];
    fleetMock.agents.data = [
      {
        client_id: "c1",
        template_id: "weekly-client-report",
        template_version: "1",
        agent_name: "acme-weekly-client-report",
        display_name: null,
        description: null,
        scheduled_task_id: null,
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      },
    ];
    renderWithI18n(<ClientSpacesView />);
    expect(screen.queryByText("Weekly Client Report")).toBeNull();
    expect(screen.getByText("Review Replies")).toBeTruthy();
  });

  it("stamps the selected template when Add is submitted", () => {
    clientsMock.data = [
      {
        id: "c1",
        display_name: "Acme",
        status: "active",
        assignments: [],
        project_count: 0,
      },
    ];
    fleetMock.templates.data = [
      { id: "review-replies", name: "Review Replies" },
    ];
    renderWithI18n(<ClientSpacesView />);

    fireEvent.change(screen.getByRole("combobox"), {
      target: { value: "review-replies" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));

    expect(fleetMock.stampMutate).toHaveBeenCalledWith(
      "review-replies",
      expect.anything(),
    );
  });

  it("shows an error message when stamping fails", () => {
    clientsMock.data = [
      {
        id: "c1",
        display_name: "Acme",
        status: "active",
        assignments: [],
        project_count: 0,
      },
    ];
    fleetMock.stampIsError = true;
    fleetMock.stampError = new Error("Couldn't add that agent.");
    renderWithI18n(<ClientSpacesView />);
    expect(screen.getByRole("alert").textContent).toContain(
      "Couldn't add that agent.",
    );
  });
});
