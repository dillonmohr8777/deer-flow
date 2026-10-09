import { afterEach, beforeEach, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import type { PropsWithChildren } from "react";

const mocks = rs.hoisted(() => ({
  tasks: {
    data: undefined as unknown[] | undefined,
    isLoading: false,
    isFetching: false,
    error: null as Error | null,
    refetch: rs.fn(),
  },
}));

rs.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(""),
}));
rs.mock("@/core/scheduled-tasks/hooks", () => {
  const mutation = () => ({ mutate: rs.fn(), isPending: false });
  return {
    useScheduledTasks: () => mocks.tasks,
    useThreadScheduledTasks: () => ({ data: undefined, isLoading: false }),
    useCreateScheduledTask: mutation,
    useUpdateScheduledTask: mutation,
    useDeleteScheduledTask: mutation,
    usePauseScheduledTask: mutation,
    useResumeScheduledTask: mutation,
    useTriggerScheduledTask: mutation,
  };
});
rs.mock("@/core/scheduled-tasks/run-history", () => ({
  useScheduledTaskRunHistory: () => ({
    data: [],
    isPending: false,
    isError: false,
    isFetching: false,
    page: 0,
    hasOlder: false,
    older: rs.fn(),
    newer: rs.fn(),
    latest: rs.fn(),
    refetch: rs.fn(),
  }),
}));
rs.mock("@/core/agents/hooks", () => ({
  useAgentsApiEnabled: () => ({ enabled: false, isLoading: false }),
}));
rs.mock("@/components/workspace/scheduled-task-schedule-input", () => ({
  ScheduledTaskScheduleInput: () => <div />,
}));
rs.mock("@/components/workspace/workspace-container", () => ({
  WorkspaceContainer: ({ children }: PropsWithChildren) => (
    <div>{children}</div>
  ),
  WorkspaceHeader: () => <div />,
  WorkspaceBody: ({ children }: PropsWithChildren) => <main>{children}</main>,
}));

import ScheduledTasksPage from "@/app/workspace/scheduled-tasks/page";
import { I18nProvider } from "@/core/i18n/context";
import type { ScheduledTask } from "@/core/scheduled-tasks/types";

const EM_DASH = String.fromCharCode(0x2014);

function Wrapper({ children }: PropsWithChildren) {
  const client = new QueryClient();
  return (
    <QueryClientProvider client={client}>
      <I18nProvider initialLocale="en-US">{children}</I18nProvider>
    </QueryClientProvider>
  );
}

function task(overrides: Partial<ScheduledTask>): ScheduledTask {
  return {
    id: "task-1",
    thread_id: null,
    context_mode: "fresh_thread_per_run",
    assistant_id: null,
    title: "Morning digest",
    prompt: "Summarize overnight work",
    schedule_type: "cron",
    schedule_spec: { cron: "0 9 * * *" },
    timezone: "UTC",
    status: "enabled",
    next_run_at: null,
    last_run_at: null,
    last_run_id: null,
    last_thread_id: null,
    last_error: null,
    run_count: 0,
    created_at: "2026-09-20T00:00:00Z",
    updated_at: "2026-09-20T00:00:00Z",
    ...overrides,
  };
}

beforeEach(() => {
  mocks.tasks.data = undefined;
  mocks.tasks.isLoading = false;
  mocks.tasks.error = null;
  mocks.tasks.refetch.mockClear();
});
afterEach(cleanup);

it("names every gap in words instead of a dash", () => {
  mocks.tasks.data = [task({})];
  render(<ScheduledTasksPage />, { wrapper: Wrapper });
  const detail = screen.getByTestId("scheduled-task-detail");
  expect(within(detail).getByText("Not scheduled")).toBeDefined();
  expect(within(detail).getByText("Never")).toBeDefined();
  expect(within(detail).getAllByText("None").length).toBeGreaterThan(0);
  expect(document.body.textContent).not.toContain(EM_DASH);
});

it("pins only the task that is running now", () => {
  mocks.tasks.data = [
    task({ id: "a", title: "Working", status: "running" }),
    task({ id: "b", title: "Waiting", status: "paused" }),
  ];
  render(<ScheduledTasksPage />, { wrapper: Wrapper });
  const running = screen.getByTestId("scheduled-task-item-a");
  const paused = screen.getByTestId("scheduled-task-item-b");
  expect(running.closest("li")?.classList.contains("pinned")).toBe(true);
  expect(paused.closest("li")?.classList.contains("pinned")).toBe(false);
  expect(within(running).getByText("Running").getAttribute("data-tone")).toBe(
    "active",
  );
});

it("says loading, empty and failed plainly", () => {
  mocks.tasks.isLoading = true;
  const { rerender } = render(<ScheduledTasksPage />, { wrapper: Wrapper });
  expect(
    within(screen.getByTestId("scheduled-task-list")).getByRole("status")
      .textContent,
  ).toContain("Loading");

  mocks.tasks.isLoading = false;
  mocks.tasks.data = [];
  rerender(<ScheduledTasksPage />);
  expect(screen.getByText(/Nothing is scheduled yet/)).toBeDefined();

  mocks.tasks.data = undefined;
  mocks.tasks.error = new Error("503 Service Unavailable");
  rerender(<ScheduledTasksPage />);
  const alert = within(
    screen.getByTestId("scheduled-task-load-error"),
  ).getByRole("alert");
  expect(alert.textContent).toContain("Failed to load scheduled tasks");
  fireEvent.click(within(alert).getByRole("button", { name: "Try again" }));
  expect(mocks.tasks.refetch).toHaveBeenCalledTimes(1);
});
