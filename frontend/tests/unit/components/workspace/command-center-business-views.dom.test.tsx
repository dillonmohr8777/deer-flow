import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";

import {
  ClientSpacesView,
  WorkflowsView,
} from "@/components/workspace/command-center/business-views";

afterEach(cleanup);

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

describe("WorkflowsView truth labels", () => {
  it("labels unknown schedule fields instead of inventing values", () => {
    render(<WorkflowsView />);
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
  });

  it("shows an empty state when no clients exist yet", () => {
    clientsMock.data = [];
    render(<ClientSpacesView />);
    expect(screen.getByText(/No clients yet/)).toBeTruthy();
  });

  it("shows a retry notice on error", () => {
    clientsMock.isError = true;
    render(<ClientSpacesView />);
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
    render(<ClientSpacesView />);

    const acmeRow = screen.getByText("Acme").closest("li");
    expect(acmeRow?.textContent).toContain("active");
    expect(acmeRow?.textContent).toContain("2 assigned");
    expect(acmeRow?.textContent).toContain("3 projects");

    const globexRow = screen.getByText("Globex").closest("li");
    expect(globexRow?.textContent).toContain("prospect");
    expect(globexRow?.textContent).toContain("0 assigned");
    expect(globexRow?.textContent).toContain("0 projects");
  });
});
