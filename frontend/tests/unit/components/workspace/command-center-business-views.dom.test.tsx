import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";

import { WorkflowsView } from "@/components/workspace/command-center/business-views";

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

describe("WorkflowsView truth labels", () => {
  it("labels unknown schedule fields instead of inventing values", () => {
    render(<WorkflowsView />);
    expect(screen.getByText("Untitled workflow")).toBeTruthy();
    expect(screen.getByText("Schedule not reported")).toBeTruthy();
    expect(screen.getByText("Not scheduled")).toBeTruthy();
    expect(screen.getByText("No runs recorded")).toBeTruthy();
  });
});
