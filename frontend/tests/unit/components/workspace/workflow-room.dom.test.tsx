import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { useState, type PropsWithChildren } from "react";

const mocks = rs.hoisted(() => ({
  user: {
    id: "owner-one",
    permissions: ["runs:read", "runs:create", "runs:cancel"],
  } as { id: string; permissions: string[] } | null,
  static: false,
  status: rs.fn(),
  catalog: rs.fn(),
  list: rs.fn(),
  read: rs.fn(),
  create: rs.fn(),
  action: rs.fn(),
  download: rs.fn(),
  handOff: rs.fn(),
}));
rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: () => ({ user: mocks.user }),
}));
rs.mock("@/core/static-mode", () => ({
  isStaticWebsiteOnly: () => mocks.static,
}));
rs.mock("@/components/ui/sidebar", () => ({
  SidebarTrigger: () => <button aria-label="Toggle sidebar" />,
}));
rs.mock("@/core/browserbase/api", () => ({
  handOffResearchDownload: mocks.handOff,
}));
rs.mock("@/core/workflows/api", () => ({
  getWorkflowStatus: mocks.status,
  getWorkflowCatalog: mocks.catalog,
  listWorkflowRuns: mocks.list,
  getWorkflowRun: mocks.read,
  createWorkflowRun: mocks.create,
  updateWorkflowRun: mocks.action,
  downloadWorkflowArtifact: mocks.download,
  isWorkflowScopeError: (error: Error) =>
    error?.message === "workspace_scope_changed",
  isAdmissionUnconfirmed: (error: Error) =>
    !["queue_full", "not_enabled", "framework_unavailable"].includes(
      error.message,
    ),
}));

import { WorkflowRoom } from "@/components/workspace/workflows/workflow-room";
import { type WorkflowRun } from "@/core/workflows/types";

import {
  WORKFLOW_FIXTURES,
  WORKFLOW_RUN,
  WORKFLOW_STATUS,
} from "../../../fixtures/workflows";

const clients: QueryClient[] = [];
function Wrapper({ children }: PropsWithChildren) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { retry: false },
          mutations: { retry: false },
        },
      }),
  );
  if (!clients.includes(client)) clients.push(client);
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
async function chooseAndRun() {
  fireEvent.click(
    await screen.findByRole("button", { name: /^Synthetic workflow 001/ }),
  );
  fireEvent.change(screen.getByLabelText("Task brief (required)"), {
    target: { value: "Actual edited task" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Run workflow" }));
}
beforeEach(() => {
  Object.values(mocks).forEach((mock) => {
    if (typeof mock === "function") mock.mockReset();
  });
  mocks.user = {
    id: "owner-one",
    permissions: ["runs:read", "runs:create", "runs:cancel"],
  };
  mocks.static = false;
  mocks.status.mockResolvedValue(WORKFLOW_STATUS);
  mocks.catalog.mockResolvedValue({ workflows: WORKFLOW_FIXTURES, total: 100 });
  mocks.list.mockResolvedValue({ runs: [] });
  mocks.read.mockResolvedValue(WORKFLOW_RUN);
  mocks.create.mockResolvedValue(WORKFLOW_RUN);
});
afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
});

describe("Workflow room behavior", () => {
  it("searches/categories the server catalog and edits a clearly synthetic example without dispatch", async () => {
    render(<WorkflowRoom />, { wrapper: Wrapper });
    await screen.findByText("100 of 100 workflow definitions");
    fireEvent.change(screen.getByLabelText("Workflow category"), {
      target: { value: "Operations" },
    });
    await screen.findByText("50 of 100 workflow definitions");
    fireEvent.change(screen.getByLabelText("Search workflows"), {
      target: { value: "100" },
    });
    await screen.findByText("1 of 100 workflow definitions");
    fireEvent.click(
      screen.getByRole("button", { name: /^Synthetic workflow 100/ }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Load synthetic example" }),
    );
    await screen.findByText(/Synthetic example loaded/);
    expect(
      screen.getByLabelText<HTMLTextAreaElement>("Task brief (required)").value,
    ).toContain("Synthetic");
    expect(mocks.create).not.toHaveBeenCalled();
    expect(
      screen.getByRole<HTMLOptionElement>("option", {
        name: "CrewAI (unavailable)",
      }).disabled,
    ).toBe(true);
  });
  it("uses the actual catalog total without assuming100 and validates required fields before dispatch", async () => {
    mocks.catalog.mockResolvedValue({
      workflows: WORKFLOW_FIXTURES.slice(0, 2),
      total: 120,
    });
    render(<WorkflowRoom />, { wrapper: Wrapper });
    await screen.findByText("2 of 120 workflow definitions");
    fireEvent.click(
      screen.getByRole("button", { name: /^Synthetic workflow 001/ }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Run workflow" }));
    await screen.findByText("Task brief is required.");
    expect(mocks.create).not.toHaveBeenCalled();
  });
  it("keeps an unconfirmed admission locked to its exact inputs and receipt on explicit retry", async () => {
    mocks.create
      .mockRejectedValueOnce(new Error("Connection lost"))
      .mockResolvedValueOnce(WORKFLOW_RUN);
    render(<WorkflowRoom />, { wrapper: Wrapper });
    await chooseAndRun();
    await screen.findByText(/The request is unconfirmed/);
    expect(
      screen.getByLabelText<HTMLTextAreaElement>("Task brief (required)")
        .disabled,
    ).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Retry same request" }));
    await screen.findByText(/completed · LangGraph · acceptance passed/);
    expect(mocks.create.mock.calls[0]?.slice(0, 3)).toEqual(
      mocks.create.mock.calls[1]?.slice(0, 3),
    );
    expect(mocks.create.mock.calls[0]?.[1]).toMatch(/^[0-9a-f-]{36}$/);
    expect(mocks.create.mock.calls[0]?.[0]).toEqual({
      workflow_id: "fixture-001",
      framework: "langgraph",
      inputs: { brief: "Actual edited task" },
    });
  });
  it("unlocks a confirmed queue rejection without claiming completion", async () => {
    mocks.create.mockRejectedValue(new Error("queue_full"));
    render(<WorkflowRoom />, { wrapper: Wrapper });
    await chooseAndRun();
    await screen.findByText(/workflow queue is full/);
    expect(
      screen.getByRole<HTMLButtonElement>("button", { name: "Run workflow" })
        .disabled,
    ).toBe(false);
    expect(
      screen.queryByRole("button", { name: "Retry same request" }),
    ).toBeNull();
    expect(screen.queryByLabelText("Workflow run")).toBeNull();
  });
  it("aborts and discards a late admission after an actor switch", async () => {
    let settle: (run: WorkflowRun) => void = () => undefined;
    mocks.create.mockImplementation(
      () =>
        new Promise<WorkflowRun>((resolve) => {
          settle = resolve;
        }),
    );
    const { rerender } = render(<WorkflowRoom />, { wrapper: Wrapper });
    await chooseAndRun();
    await waitFor(() => expect(mocks.create).toHaveBeenCalledTimes(1));
    const signal = mocks.create.mock.calls[0]?.[3] as AbortSignal;
    mocks.user = { id: "owner-two", permissions: ["runs:read", "runs:create"] };
    mocks.status.mockResolvedValue({
      ...WORKFLOW_STATUS,
      owner_scope: "scope-two",
    });
    rerender(<WorkflowRoom />);
    await waitFor(() =>
      expect(
        mocks.status.mock.calls.some((call) => call[0] === "owner-two"),
      ).toBe(true),
    );
    settle(WORKFLOW_RUN);
    await waitFor(() => expect(signal.aborted).toBe(true));
    expect(screen.queryByLabelText("Workflow run")).toBeNull();
    expect(mocks.handOff).not.toHaveBeenCalled();
    expect(
      clients[0]?.getQueryData([
        "workflows",
        "owner-one",
        "scope-one",
        "runs",
        WORKFLOW_RUN.id,
      ]),
    ).toBeUndefined();
  });
  it("fences a previous workspace's late admission while the actor stays the same", async () => {
    let settle: (run: WorkflowRun) => void = () => undefined;
    mocks.create.mockImplementation(
      () =>
        new Promise<WorkflowRun>((resolve) => {
          settle = resolve;
        }),
    );
    render(<WorkflowRoom />, { wrapper: Wrapper });
    await chooseAndRun();
    await waitFor(() => expect(mocks.create).toHaveBeenCalledTimes(1));
    const signal = mocks.create.mock.calls[0]?.[3] as AbortSignal;
    mocks.status.mockResolvedValue({
      ...WORKFLOW_STATUS,
      owner_scope: "scope-two",
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Refresh workflow room" }),
    );
    await waitFor(() =>
      expect(
        mocks.list.mock.calls.some((call) => call[0] === "scope-two"),
      ).toBe(true),
    );
    settle(WORKFLOW_RUN);
    await waitFor(() => expect(signal.aborted).toBe(true));
    expect(screen.queryByLabelText("Workflow run")).toBeNull();
    expect(mocks.handOff).not.toHaveBeenCalled();
  });
  it("resumes an actual interrupted record using its original run and shows recorded model/usage", async () => {
    const interrupted = {
      ...WORKFLOW_RUN,
      status: "interrupted" as const,
      accepted: false,
      output: null,
    };
    mocks.list.mockResolvedValue({ runs: [interrupted] });
    mocks.read.mockResolvedValue(interrupted);
    mocks.action.mockImplementation(async () => {
      mocks.read.mockResolvedValue(WORKFLOW_RUN);
      mocks.list.mockResolvedValue({ runs: [WORKFLOW_RUN] });
      return WORKFLOW_RUN;
    });
    render(<WorkflowRoom />, { wrapper: Wrapper });
    fireEvent.click(
      await screen.findByRole("button", {
        name: /^Synthetic saved run interrupted/,
      }),
    );
    await screen.findByText(/remaining budget/);
    fireEvent.click(
      screen.getByRole("button", { name: "Resume interrupted run" }),
    );
    await screen.findByText(/acceptance passed/);
    expect(mocks.action).toHaveBeenCalledWith(
      "owned-run",
      "resume",
      "scope-one",
      expect.any(AbortSignal),
    );
    await screen.findByText("Model gpt-6.1-sol · effort high");
    await screen.findByText(/Cost unavailable/);
    expect(mocks.create).not.toHaveBeenCalled();
  });
  it("renders unaccepted output as plain text and never offers an accepted artifact", async () => {
    const failed = {
      ...WORKFLOW_RUN,
      accepted: false,
      artifact: { bytes: 2, sha256: "a".repeat(64) },
    };
    mocks.list.mockResolvedValue({ runs: [failed] });
    mocks.read.mockResolvedValue(failed);
    render(<WorkflowRoom />, { wrapper: Wrapper });
    fireEvent.click(
      await screen.findByRole("button", {
        name: /^Synthetic saved run completed/,
      }),
    );
    await screen.findByText(/output not accepted/);
    expect(screen.getByText(/Synthetic verified result/).tagName).toBe("PRE");
    expect(document.querySelector("script")).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Download accepted artifact" }),
    ).toBeNull();
  });
  it("labels unresolved model usage as a known minimum rather than final totals", async () => {
    const incomplete = {
      ...WORKFLOW_RUN,
      usage: {
        model_calls: 2,
        input_tokens: 0,
        output_tokens: 0,
        cost: null,
        complete: false,
        unknown_model_calls: 2,
      },
    };
    mocks.list.mockResolvedValue({ runs: [incomplete] });
    mocks.read.mockResolvedValue(incomplete);
    render(<WorkflowRoom />, { wrapper: Wrapper });
    fireEvent.click(
      await screen.findByRole("button", {
        name: /^Synthetic saved run completed/,
      }),
    );
    await screen.findByText(/Known minimum: 0 input tokens/);
    await screen.findByText(/2 attempts have unresolved usage/);
  });
  it("aborts an old owner's artifact and never hands a late download to the browser", async () => {
    let settle: (blob: Blob) => void = () => undefined;
    const completed = {
      ...WORKFLOW_RUN,
      artifact: { bytes: 2, sha256: "a".repeat(64) },
    };
    mocks.list.mockResolvedValue({ runs: [completed] });
    mocks.read.mockResolvedValue(completed);
    mocks.download.mockImplementation(
      () =>
        new Promise<Blob>((resolve) => {
          settle = resolve;
        }),
    );
    const { rerender } = render(<WorkflowRoom />, { wrapper: Wrapper });
    fireEvent.click(
      await screen.findByRole("button", {
        name: /^Synthetic saved run completed/,
      }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Download accepted artifact" }),
    );
    await waitFor(() => expect(mocks.download).toHaveBeenCalledTimes(1));
    const signal = mocks.download.mock.calls[0]?.[3] as AbortSignal;
    mocks.user = { id: "owner-two", permissions: ["runs:read"] };
    mocks.list.mockResolvedValue({ runs: [] });
    mocks.status.mockResolvedValue({
      ...WORKFLOW_STATUS,
      owner_scope: "scope-two",
    });
    rerender(<WorkflowRoom />);
    await waitFor(() => expect(signal.aborted).toBe(true));
    settle(new Blob(["{}"]));
    await waitFor(() =>
      expect(
        mocks.list.mock.calls.some((call) => call[0] === "scope-two"),
      ).toBe(true),
    );
    expect(mocks.handOff).not.toHaveBeenCalled();
  });
  it("does not call APIs for anonymous/static views, and browser unavailable/read-only views cannot dispatch", async () => {
    mocks.user = null;
    const first = render(<WorkflowRoom />, { wrapper: Wrapper });
    await screen.findByText(/authenticated workflow read access/);
    expect(mocks.status).not.toHaveBeenCalled();
    first.unmount();
    mocks.user = { id: "owner-one", permissions: ["runs:read"] };
    mocks.static = true;
    const second = render(<WorkflowRoom />, { wrapper: Wrapper });
    await screen.findByText(/authenticated workflow read access/);
    expect(mocks.status).not.toHaveBeenCalled();
    second.unmount();
    mocks.static = false;
    mocks.status.mockResolvedValue({
      ...WORKFLOW_STATUS,
      frameworks: {
        ...WORKFLOW_STATUS.frameworks,
        browser: { available: false, detail: "Disabled" },
      },
    });
    render(<WorkflowRoom />, { wrapper: Wrapper });
    fireEvent.click(
      await screen.findByRole("button", { name: /^Synthetic workflow 010/ }),
    );
    await screen.findByText(/Public browser evidence is unavailable/);
    await screen.findByText("You have read-only access.");
    expect(
      screen.getByRole<HTMLButtonElement>("button", { name: "Run workflow" })
        .disabled,
    ).toBe(true);
    expect(mocks.create).not.toHaveBeenCalled();
  });
});
