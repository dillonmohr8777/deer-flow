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
rs.mock("@/components/workspace/workspace-container", () => ({
  WorkspaceContainer: ({ children }: PropsWithChildren) => (
    <div>{children}</div>
  ),
  WorkspaceHeader: () => <div />,
  WorkspaceBody: ({ children }: PropsWithChildren) => <main>{children}</main>,
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
/** The open run's status line, in the detail sheet, not the list row. */
async function detailSays(text: string) {
  await waitFor(() =>
    expect(
      within(screen.getByLabelText("Workflow run")).getByRole("status")
        .textContent,
    ).toBe(text),
  );
}
async function chooseAndRun() {
  fireEvent.click(
    await screen.findByRole("button", { name: /^Synthetic workflow 001/ }),
  );
  fireEvent.change(screen.getByLabelText("Task brief"), {
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
      screen.getByRole("button", { name: "Fill in sample inputs" }),
    );
    await screen.findByText(/Sample inputs filled in/);
    expect(
      screen.getByLabelText<HTMLTextAreaElement>("Task brief").value,
    ).toContain("Synthetic");
    expect(mocks.create).not.toHaveBeenCalled();
    expect(
      screen.getByRole<HTMLOptionElement>("option", {
        name: "CrewAI (not set up)",
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
      screen.getByLabelText<HTMLTextAreaElement>("Task brief").disabled,
    ).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Retry same request" }));
    await detailSays("Accepted · LangGraph");
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
        name: /^Synthetic saved run Interrupted/,
      }),
    );
    await screen.findByText(/remaining budget/);
    fireEvent.click(
      screen.getByRole("button", { name: "Resume interrupted run" }),
    );
    await detailSays("Accepted · LangGraph");
    expect(mocks.action).toHaveBeenCalledWith(
      "owned-run",
      "resume",
      "scope-one",
      expect.any(AbortSignal),
    );
    await screen.findByText(", high effort", { exact: false });
    expect(screen.getByText("gpt-6.1-sol").className).toContain("font-mono");
    await screen.findByText("Unavailable");
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
        name: /^Synthetic saved run Not accepted/,
      }),
    );
    await detailSays("Not accepted · LangGraph");
    await screen.findByText("Result, not accepted");
    expect(screen.getByText(/Synthetic verified result/).tagName).toBe("P");
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
        name: /^Synthetic saved run Accepted/,
      }),
    );
    await screen.findByText("Input tokens, at least");
    await screen.findByText(/Known minimum\. 2 attempts have unresolved usage/);
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
        name: /^Synthetic saved run Accepted/,
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
    await screen.findByText(/page capture is not set up/);
    await screen.findByText(
      "You can read workflows here, but running them needs more access.",
    );
    expect(
      screen.getByRole<HTMLButtonElement>("button", { name: "Run workflow" })
        .disabled,
    ).toBe(true);
    expect(mocks.create).not.toHaveBeenCalled();
  });
  it("names a failed read in plain words with one next step, never the raw code", async () => {
    mocks.status.mockRejectedValueOnce(new Error("workflow_request_failed"));
    render(<WorkflowRoom />, { wrapper: Wrapper });
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Workflows could not be loaded.");
    expect(alert.textContent).toContain("The workflow service did not answer.");
    expect(document.body.textContent).not.toContain("workflow_request_failed");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await screen.findByText("Your runs");
    expect(mocks.status).toHaveBeenCalledTimes(2);
  });
  it("hides an unknown server code behind a sentence and keeps a readable one", async () => {
    mocks.list.mockRejectedValueOnce(new Error("some_internal_code"));
    render(<WorkflowRoom />, { wrapper: Wrapper });
    await screen.findByText("Your runs could not be loaded.");
    expect(document.body.textContent).not.toContain("some_internal_code");
    await screen.findByText(
      "The workflow service could not complete this request.",
    );
  });
  it("files each saved run with its state in words, and pins only a running one", async () => {
    mocks.list.mockResolvedValue({
      runs: [
        { ...WORKFLOW_RUN, id: "a", title: "Audit", status: "running" },
        { ...WORKFLOW_RUN, id: "b", title: "Recap" },
        {
          ...WORKFLOW_RUN,
          id: "c",
          title: "Site QA",
          status: "failed",
          accepted: false,
          error: "Model-call budget reached before review",
        },
      ],
    });
    render(<WorkflowRoom />, { wrapper: Wrapper });
    const running = await screen.findByRole("button", {
      name: /^Audit Running/,
    });
    expect(running.closest("li")?.classList.contains("pinned")).toBe(true);
    const accepted = screen.getByRole("button", { name: /^Recap Accepted/ });
    expect(accepted.closest("li")?.classList.contains("pinned")).toBe(false);
    const failed = screen.getByRole("button", { name: /^Site QA Failed/ });
    expect(failed.textContent).toContain(
      "Model-call budget reached before review",
    );
    expect(failed.querySelector("time")?.getAttribute("dateTime")).toBe(
      new Date(WORKFLOW_RUN.created_at).toISOString(),
    );
    expect(document.body.textContent).not.toMatch(/\bcompleted ·/);
  });
  it("says what will appear when there are no runs and leads to the catalog", async () => {
    render(<WorkflowRoom />, { wrapper: Wrapper });
    await screen.findByText("No runs yet");
    expect(
      screen
        .getByRole("link", { name: "Choose a workflow" })
        .getAttribute("href"),
    ).toBe("#workflow-catalog");
    expect(document.getElementById("workflow-catalog")).not.toBeNull();
  });
  it("stamps a microsecond run time as a valid <time dateTime>", async () => {
    mocks.list.mockResolvedValue({
      runs: [
        { ...WORKFLOW_RUN, created_at: "2026-09-30T08:00:00.123456+00:00" },
      ],
    });
    render(<WorkflowRoom />, { wrapper: Wrapper });
    const row = await screen.findByRole("button", {
      name: /^Synthetic saved run Accepted/,
    });
    expect(row.querySelector("time")?.getAttribute("dateTime")).toBe(
      "2026-09-30T08:00:00.123Z",
    );
  });
  it("gives each code the engine stores its own words in the list and the detail", async () => {
    const failed = (id: string, error: string) => ({
      ...WORKFLOW_RUN,
      id,
      title: `Run ${id}`,
      status: "failed" as const,
      accepted: false,
      error,
    });
    const runs = [
      failed("a", "workflow_independent_review_rejected"),
      failed("b", "workflow_call_limit_exceeded"),
    ];
    mocks.list.mockResolvedValue({ runs });
    mocks.read.mockImplementation((id: string) =>
      Promise.resolve(runs.find((run) => run.id === id)),
    );
    render(<WorkflowRoom />, { wrapper: Wrapper });
    const acceptance = "independent reviewer rejected the draft";
    const budget = "used all of its model calls";
    const a = await screen.findByRole("button", { name: /^Run a Failed/ });
    const b = screen.getByRole("button", { name: /^Run b Failed/ });
    expect(a.textContent).toContain(acceptance);
    expect(b.textContent).toContain(budget);
    fireEvent.click(b);
    const detail = await screen.findByLabelText("Workflow run");
    await waitFor(() => expect(detail.textContent).toContain(budget));
    expect(detail.textContent).not.toContain("workflow_call_limit_exceeded");
  });
  it("says a run at its resume limit cannot be resumed again", async () => {
    const interrupted = {
      ...WORKFLOW_RUN,
      status: "interrupted" as const,
      accepted: false,
    };
    mocks.list.mockResolvedValue({ runs: [interrupted] });
    mocks.read.mockResolvedValue(interrupted);
    mocks.action.mockRejectedValue(new Error("resume_limit"));
    render(<WorkflowRoom />, { wrapper: Wrapper });
    fireEvent.click(
      await screen.findByRole("button", {
        name: /^Synthetic saved run Interrupted/,
      }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Resume interrupted run" }),
    );
    await screen.findByText(/cannot be resumed again/);
  });
  it("reads the step journal as one plain row per step, never raw codes or worker ids", async () => {
    const worker = "wf_3f9a1c0d2e4b5a6978c1d2e3f4a5b6c7";
    const failed: WorkflowRun = {
      ...WORKFLOW_RUN,
      status: "failed",
      accepted: false,
      output: null,
      error: "run_model_budget_exhausted",
      steps: [
        {
          name: "validate",
          status: "completed",
          detail: "input_schema_validated",
        },
        {
          name: "plan",
          status: "running",
          worker_id: worker,
          model: "gpt-6.1-sol",
          effort: "low",
        },
        {
          name: "plan",
          status: "completed",
          worker_id: worker,
          model: "gpt-6.1-sol",
          effort: "low",
        },
        {
          name: "draft",
          status: "running",
          worker_id: worker,
          model: "gpt-6.1-sol",
          effort: "medium",
        },
        { name: "mystery", status: "completed", detail: "some_internal_code" },
      ],
    };
    mocks.list.mockResolvedValue({ runs: [failed] });
    mocks.read.mockResolvedValue(failed);
    render(<WorkflowRoom />, { wrapper: Wrapper });
    fireEvent.click(
      await screen.findByRole("button", {
        name: /^Synthetic saved run Failed/,
      }),
    );
    const list = await screen.findByRole("list", {
      name: "Recorded workflow steps",
    });
    const rows = within(list).getAllByRole("listitem");
    expect(rows.map((row) => row.textContent)).toEqual([
      "Check the inputsEvery field is present and inside its limits.Done",
      "Plan the workgpt-6.1-sol, low effortDone",
      "Draft the resultgpt-6.1-sol, medium effortStopped here",
      "MysteryDone",
    ]);
    const sheet = screen.getByLabelText("Workflow run");
    expect(sheet.textContent).not.toContain(worker);
    expect(sheet.textContent).not.toMatch(/_[a-z]+_/);
    expect(within(sheet).getByText("owned-run").className).toContain(
      "font-mono",
    );
  });
  it("has words for every workflow_ code the engine raises", async () => {
    // Codes engine.py raises into a failed run's stored error.
    const codes = [
      "workflow_independent_review_rejected",
      "workflow_output_not_accepted",
      "workflow_review_criteria_incomplete",
      "workflow_model_call_failed",
      "workflow_call_limit_exceeded",
      "workflow_context_too_large",
      "workflow_output_provenance_invalid",
      "workflow_browser_unavailable",
      "workflow_browser_evidence_invalid",
      "workflow_usage_receipt_invalid",
    ];
    const { explanation } =
      await import("@/components/workspace/workflows/workflow-words");
    const words = codes.map((code) => explanation(new Error(code)));
    for (const text of words) {
      expect(text).not.toBe(
        "The workflow service could not complete this request.",
      );
    }
    expect(new Set(words).size).toBe(codes.length);
  });
  it("prices a sub-cent run and words an unknown attempt count", async () => {
    const run = {
      ...WORKFLOW_RUN,
      usage: {
        ...WORKFLOW_RUN.usage,
        cost: 0.0042,
        complete: false,
        unknown_model_calls: 0,
      },
    };
    mocks.list.mockResolvedValue({ runs: [run] });
    mocks.read.mockResolvedValue(run);
    render(<WorkflowRoom />, { wrapper: Wrapper });
    fireEvent.click(
      await screen.findByRole("button", {
        name: /^Synthetic saved run Accepted/,
      }),
    );
    const detail = await screen.findByLabelText("Workflow run");
    await waitFor(() => expect(detail.textContent).toContain("Under $0.01"));
    expect(detail.textContent).toContain("Some attempts have unresolved");
    expect(detail.textContent).not.toContain("0 attempts");
  });
});
