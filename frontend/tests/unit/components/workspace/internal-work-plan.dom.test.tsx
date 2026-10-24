import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";

import { InternalWorkPlan } from "@/components/workspace/inbox/internal-work-plan";
import type { WorkPlan } from "@/core/client-portal/work-plan";

const mocks = rs.hoisted(() => ({ fetch: rs.fn() }));
rs.mock("@/core/api/fetcher", () => ({ fetch: mocks.fetch }));
rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "" }));

const props = {
  userId: "synthetic-staff",
  workspace: "synthetic-workspace",
  clientId: "synthetic-client",
  requestId: "synthetic-request",
  requests: [
    { id: "synthetic-request", subject: "Current request" },
    { id: "synthetic-dependency", subject: "Earlier request" },
  ],
};
const plan: WorkPlan = {
  outcome: "Synthetic saved outcome",
  assignee_user_id: null,
  due_at: null,
  dependency_thread_ids: [],
  verifier_user_id: null,
  status: "planned",
  next_action: "Check the synthetic source",
  evidence_refs: [],
};
function record(
  requestId = props.requestId,
  revision = 7,
  saved: WorkPlan | null = plan,
) {
  return {
    schema: "internal_work_plan.v1",
    revision,
    plan: saved,
    recorded_by_user_id: saved ? props.userId : null,
    recorded_at: saved ? "2026-10-24T12:00:00Z" : null,
    verification: "staff_recorded_unverified",
    source: { table: "board_portal", id: requestId },
  };
}
const response = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
function calls(method: string) {
  return mocks.fetch.mock.calls.filter(
    ([, options]) => (options as RequestInit).method === method,
  );
}
function change(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}
function save() {
  fireEvent.click(screen.getByRole("button", { name: "Save work plan" }));
}
function reload() {
  fireEvent.click(screen.getByRole("button", { name: "Reload plan" }));
}
function choose(label: string, name: RegExp) {
  const picker = screen.getByLabelText<HTMLSelectElement>(label);
  const option = within(picker).getByRole<HTMLOptionElement>("option", {
    name,
  });
  fireEvent.change(picker, { target: { value: option.value } });
}
let queryClient: QueryClient;
function view(overrides: Partial<typeof props> = {}) {
  return (
    <QueryClientProvider client={queryClient}>
      <InternalWorkPlan {...props} {...overrides} />
    </QueryClientProvider>
  );
}
async function ready() {
  await waitFor(() =>
    expect(screen.getByLabelText<HTMLTextAreaElement>("Outcome").value).toBe(
      plan.outcome,
    ),
  );
}

describe("InternalWorkPlan recorded staff plans", () => {
  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    mocks.fetch.mockReset();
    mocks.fetch.mockImplementation(
      async (_url: string, options: RequestInit) => {
        if (options.method === "PUT") {
          const body = JSON.parse(options.body as string) as {
            expected_revision: number;
            plan: WorkPlan;
          };
          return response(
            record(props.requestId, body.expected_revision + 1, body.plan),
          );
        }
        return response(record());
      },
    );
  });
  afterEach(() => {
    cleanup();
    queryClient.clear();
  });

  it("loads the scoped plan and saves its full replacement with the plan's independent revision", async () => {
    render(view());
    await ready();
    const [url, options] = calls("GET")[0]!;
    expect(url).toBe("/api/client-portal/threads/synthetic-request/work-plan");
    expect(options).toMatchObject({
      headers: { "X-Portal-Workspace": props.workspace },
      cache: "no-store",
    });
    change("Outcome", "Revised synthetic outcome");
    choose("Owner", /^Me$/);
    choose("Verifier", /^Me$/);
    fireEvent.click(screen.getByRole("checkbox", { name: "Earlier request" }));
    const due = "2026-10-25T14:30:00";
    fireEvent.change(screen.getByLabelText(/Due date/), {
      target: { value: due },
    });
    save();
    await waitFor(() => expect(calls("PUT").length).toBe(1));
    expect(
      JSON.parse((calls("PUT")[0]![1] as RequestInit).body as string),
    ).toEqual({
      expected_revision: 7,
      plan: {
        ...plan,
        outcome: "Revised synthetic outcome",
        assignee_user_id: props.userId,
        verifier_user_id: props.userId,
        dependency_thread_ids: ["synthetic-dependency"],
        due_at: new Date(due).toISOString(),
      },
    });
    await waitFor(() =>
      expect(
        screen.getByRole<HTMLButtonElement>("button", {
          name: "Save work plan",
        }).disabled,
      ).toBe(false),
    );
    change("Next action", "Second synthetic action");
    save();
    await waitFor(() => expect(calls("PUT").length).toBe(2));
    expect(
      JSON.parse((calls("PUT")[1]![1] as RequestInit).body as string)
        .expected_revision,
    ).toBe(8);
  });

  for (const status of [409, 503]) {
    it(`retains edits after ${status}, makes no automatic retry, and reloads only explicitly`, async () => {
      let current = record();
      mocks.fetch.mockImplementation(
        async (_url: string, options: RequestInit) =>
          options.method === "PUT"
            ? response({ detail: `Synthetic save failure ${status}` }, status)
            : response(current),
      );
      render(view());
      await ready();
      change("Outcome", "Keep this unsaved edit");
      save();
      await screen.findByText(new RegExp(`Synthetic save failure ${status}`));
      expect(screen.getByLabelText<HTMLTextAreaElement>("Outcome").value).toBe(
        "Keep this unsaved edit",
      );
      expect(calls("PUT").length).toBe(1);
      expect(calls("GET").length).toBe(1);
      current = record(props.requestId, 11, {
        ...plan,
        outcome: "Fresh recorded outcome",
      });
      reload();
      await waitFor(() =>
        expect(
          screen.getByLabelText<HTMLTextAreaElement>("Outcome").value,
        ).toBe("Fresh recorded outcome"),
      );
      expect(calls("GET").length).toBe(2);
      expect(calls("PUT").length).toBe(1);
    });
  }

  it("blocks reported completion without evidence, then saves a complete evidenced plan", async () => {
    render(view());
    await ready();
    choose("Status", /Reported complete/i);
    save();
    await screen.findByText(
      /Reported completion requires an evidence reference/,
    );
    expect(calls("PUT").length).toBe(0);
    fireEvent.click(
      screen.getByRole("button", { name: "Add evidence reference" }),
    );
    change("Evidence reference 1", "https://synthetic.invalid/delivery/1");
    choose("Evidence kind 1", /^Delivery$/);
    save();
    await waitFor(() => expect(calls("PUT").length).toBe(1));
    await screen.findByText(/Saved work plan revision 8/);
    const payload = JSON.parse(
      (calls("PUT")[0]![1] as RequestInit).body as string,
    );
    expect(payload.plan.status).toBe("reported_complete");
    expect(payload.plan.evidence_refs).toEqual([
      { kind: "delivery", reference: "https://synthetic.invalid/delivery/1" },
    ]);
  });

  it("preserves opaque saved participants and dependencies without inventing a directory", async () => {
    const saved = {
      ...plan,
      assignee_user_id: "synthetic-opaque-owner",
      verifier_user_id: "synthetic-opaque-verifier",
      dependency_thread_ids: ["synthetic-unlisted-request"],
    };
    mocks.fetch.mockResolvedValue(response(record(props.requestId, 7, saved)));
    render(view());
    await ready();
    expect(
      within(screen.getByLabelText("Owner")).getByRole("option", {
        name: /Unassigned/i,
      }),
    ).toBeTruthy();
    expect(
      within(screen.getByLabelText("Owner")).getByRole("option", {
        name: /^Me$/,
      }),
    ).toBeTruthy();
    save();
    await waitFor(() => expect(calls("PUT").length).toBe(1));
    expect(
      JSON.parse((calls("PUT")[0]![1] as RequestInit).body as string).plan,
    ).toEqual(saved);
  });

  for (const field of [
    "requestId",
    "userId",
    "workspace",
    "clientId",
  ] as const) {
    it(`suppresses a late load after ${field} changes`, async () => {
      const old = deferred<Response>();
      const fresh = deferred<Response>();
      mocks.fetch
        .mockImplementationOnce(() => old.promise)
        .mockImplementationOnce(() => fresh.promise);
      const { rerender } = render(view());
      await waitFor(() => expect(calls("GET").length).toBe(1));
      const next = { [field]: `synthetic-new-${field}` };
      rerender(view(next));
      await waitFor(() => expect(calls("GET").length).toBe(2));
      await act(async () => {
        old.resolve(response(record()));
      });
      expect(screen.queryByDisplayValue(plan.outcome)).toBeNull();
      await act(async () => {
        fresh.resolve(
          response(
            record(field === "requestId" ? next[field]! : props.requestId, 0, {
              ...plan,
              outcome: "Fresh scope outcome",
            }),
          ),
        );
      });
      await screen.findByDisplayValue("Fresh scope outcome");
      expect(screen.queryByDisplayValue(plan.outcome)).toBeNull();
    });

    it(`suppresses a late save after ${field} changes`, async () => {
      const pending = deferred<Response>();
      mocks.fetch.mockImplementation(
        async (url: string, options: RequestInit) => {
          if (options.method === "PUT") return pending.promise;
          const requestId = decodeURIComponent(url.split("/").at(-2)!);
          return response(
            record(requestId, 7, {
              ...plan,
              outcome:
                calls("GET").length > 1 ? "Fresh scope outcome" : plan.outcome,
            }),
          );
        },
      );
      const { rerender } = render(view());
      await ready();
      change("Outcome", "Old scope save");
      save();
      await waitFor(() => expect(calls("PUT").length).toBe(1));
      rerender(view({ [field]: `synthetic-new-${field}` }));
      await screen.findByDisplayValue("Fresh scope outcome");
      await act(async () => {
        pending.resolve(
          response(
            record(props.requestId, 8, { ...plan, outcome: "Old scope save" }),
          ),
        );
      });
      expect(screen.getByLabelText<HTMLTextAreaElement>("Outcome").value).toBe(
        "Fresh scope outcome",
      );
      expect(calls("PUT").length).toBe(1);
    });
  }

  it("shows a failed initial load without retrying and recovers through Reload plan", async () => {
    mocks.fetch
      .mockResolvedValueOnce(
        response({ detail: "Synthetic read unavailable" }, 503),
      )
      .mockResolvedValueOnce(response(record()));
    render(view());
    await screen.findByText("Synthetic read unavailable");
    expect(screen.queryByRole("button", { name: "Save work plan" })).toBeNull();
    expect(calls("GET").length).toBe(1);
    reload();
    await ready();
    expect(calls("GET").length).toBe(2);
  });

  it("creates an absent plan from revision zero after required fields are entered", async () => {
    mocks.fetch.mockImplementation(
      async (_url: string, options: RequestInit) => {
        if (options.method === "GET")
          return response(record(props.requestId, 0, null));
        const body = JSON.parse(options.body as string) as { plan: WorkPlan };
        return response(record(props.requestId, 1, body.plan));
      },
    );
    render(view());
    await screen.findByText("No recorded plan yet.");
    save();
    await screen.findByRole("alert");
    expect(calls("PUT").length).toBe(0);
    change("Outcome", "A synthetic first outcome");
    change("Next action", "A synthetic first action");
    save();
    await screen.findByText(/Saved work plan revision 1/);
    expect(
      JSON.parse((calls("PUT")[0]![1] as RequestInit).body as string)
        .expected_revision,
    ).toBe(0);
  });

  it("preserves the saved due timestamp exactly when another field is edited", async () => {
    const due = "2026-11-01T01:30:42.125-04:00";
    mocks.fetch.mockImplementation(
      async (_url: string, options: RequestInit) => {
        if (options.method === "GET")
          return response(record(props.requestId, 7, { ...plan, due_at: due }));
        const body = JSON.parse(options.body as string) as { plan: WorkPlan };
        return response(record(props.requestId, 8, body.plan));
      },
    );
    render(view());
    await ready();
    change("Outcome", "Another synthetic outcome");
    save();
    await screen.findByText(/Saved work plan revision 8/);
    expect(
      JSON.parse((calls("PUT")[0]![1] as RequestInit).body as string).plan
        .due_at,
    ).toBe(due);
  });

  it("aborts an outstanding read on unmount", async () => {
    const pending = deferred<Response>();
    mocks.fetch.mockImplementationOnce(() => pending.promise);
    const { unmount } = render(view());
    await waitFor(() => expect(calls("GET").length).toBe(1));
    const signal = (calls("GET")[0]![1] as RequestInit).signal;
    unmount();
    expect(signal?.aborted).toBe(true);
    await act(async () => {
      pending.resolve(response(record()));
    });
    expect(calls("PUT").length).toBe(0);
  });
});
