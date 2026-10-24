import { beforeEach, describe, expect, rs, test } from "@rstest/core";

rs.mock("@/core/api/fetcher", () => ({ fetch: rs.fn() }));
rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "/backend" }));

import { fetch as fetcher } from "@/core/api/fetcher";
import {
  getWorkPlan,
  getWorkPlanParticipants,
  putWorkPlan,
  validateWorkPlan,
  type WorkPlan,
} from "@/core/client-portal/work-plan";

const mockedFetch = rs.mocked(fetcher);
const scope = { workspace: "workspace-1", requestId: "request/1" };
const plan: WorkPlan = {
  outcome: "A recorded outcome",
  assignee_user_id: null,
  due_at: null,
  dependency_thread_ids: [],
  verifier_user_id: null,
  status: "planned",
  next_action: "Review the source",
  evidence_refs: [],
};
const record = {
  schema: "internal_work_plan.v1",
  revision: 1,
  plan,
  recorded_by_user_id: "staff-1",
  recorded_at: "2026-10-24T12:00:00Z",
  verification: "staff_recorded_unverified",
  source: { table: "board_portal", id: scope.requestId },
};
const respond = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status });
const teammate = {
  user_id: "staff-2",
  email: "staff2@synthetic.invalid",
  role: "account_manager",
};
const directory = {
  schema: "work_plan_participants.v1",
  source: { thread_id: scope.requestId },
  plan_revision: 1,
  items: [teammate],
  selected_items: [],
  limit: 50,
  has_more: true,
  next_cursor: "opaque+/=cursor",
};
beforeEach(() => {
  mockedFetch.mockReset();
});

describe("work plan participant directory", () => {
  test("fetches the independent scoped page and encodes only limit/cursor", async () => {
    const signal = new AbortController().signal;
    mockedFetch.mockResolvedValueOnce(respond(directory));
    expect(
      await getWorkPlanParticipants({ ...scope, signal, cursor: "prior+/=" }),
    ).toEqual(directory);
    expect(mockedFetch).toHaveBeenCalledWith(
      "/backend/api/client-portal/threads/request%2F1/work-plan/participants?limit=50&cursor=prior%2B%2F%3D",
      {
        method: "GET",
        headers: { "X-Portal-Workspace": scope.workspace },
        cache: "no-store",
        signal,
      },
    );
  });

  test("accepts eligible saved people outside the page and terminal bounded pages", async () => {
    const body = {
      ...directory,
      plan_revision: 2147483647,
      items: [],
      selected_items: [teammate],
      limit: 100,
      has_more: false,
      next_cursor: null,
    };
    mockedFetch.mockResolvedValueOnce(respond(body));
    expect(await getWorkPlanParticipants({ ...scope, limit: 100 })).toEqual(
      body,
    );
  });

  test("rejects malformed, leaking, duplicate, over-limit and mismatched source pages", async () => {
    for (const patch of [
      { schema: "users.v1" },
      { plan_revision: undefined },
      { plan_revision: -1 },
      { plan_revision: 1.5 },
      { plan_revision: 2147483648 },
      { source: { thread_id: "other-request" } },
      { source: { ...directory.source, client_id: "other-client" } },
      { items: [{ ...teammate, profile: "private" }] },
      { items: [{ ...teammate, role: "contributor" }] },
      { items: [{ ...teammate, email: " " }] },
      { items: [{ ...teammate, email: "a".repeat(321) }] },
      { items: [teammate, teammate] },
      { selected_items: [teammate, teammate] },
      {
        selected_items: [
          teammate,
          { ...teammate, user_id: "3" },
          { ...teammate, user_id: "4" },
        ],
      },
      {
        selected_items: [{ ...teammate, email: "different@synthetic.invalid" }],
      },
      {
        items: Array.from({ length: 51 }, (_, index) => ({
          ...teammate,
          user_id: String(index),
        })),
      },
      { limit: 100 },
      { has_more: false },
      { next_cursor: null },
      { next_cursor: "a".repeat(513) },
      { items: [] },
      { extra: "private" },
    ]) {
      mockedFetch.mockResolvedValueOnce(respond({ ...directory, ...patch }));
      await expect(getWorkPlanParticipants(scope)).rejects.toThrow(
        "invalid teammate directory",
      );
    }
    mockedFetch.mockResolvedValueOnce(new Response("not-json"));
    await expect(getWorkPlanParticipants(scope)).rejects.toThrow(
      "invalid teammate directory",
    );
    mockedFetch.mockResolvedValueOnce(respond(directory));
    await expect(
      getWorkPlanParticipants({ ...scope, cursor: directory.next_cursor }),
    ).rejects.toThrow("invalid teammate directory");
  });

  test("bounds page inputs before fetching and never retries directory errors", async () => {
    for (const limit of [0, 101, 1.5, NaN])
      await expect(
        getWorkPlanParticipants({ ...scope, limit }),
      ).rejects.toThrow("Invalid teammate page request");
    for (const cursor of ["", "a".repeat(513)])
      await expect(
        getWorkPlanParticipants({ ...scope, cursor }),
      ).rejects.toThrow("Invalid teammate page request");
    expect(mockedFetch).not.toHaveBeenCalled();
    for (const status of [404, 503]) {
      mockedFetch.mockResolvedValueOnce(
        respond({ detail: "private details" }, status),
      );
      await expect(getWorkPlanParticipants(scope)).rejects.toThrow(
        `Could not load eligible teammates (${status})`,
      );
    }
    expect(mockedFetch).toHaveBeenCalledTimes(2);
  });

  test("rejects a late response even when its transport ignores cancellation", async () => {
    const controller = new AbortController();
    mockedFetch.mockImplementationOnce(async () => {
      controller.abort();
      return respond(directory);
    });
    await expect(
      getWorkPlanParticipants({ ...scope, signal: controller.signal }),
    ).rejects.toHaveProperty("name", "AbortError");
  });
});

describe("work plan transport", () => {
  test("GET forwards workspace, escaped request, no-store and abort signal", async () => {
    const signal = new AbortController().signal;
    mockedFetch.mockResolvedValueOnce(
      respond({ ...record, revision: 0, plan: null }),
    );
    expect(await getWorkPlan({ ...scope, signal })).toEqual({
      ...record,
      revision: 0,
      plan: null,
    });
    expect(mockedFetch).toHaveBeenCalledWith(
      "/backend/api/client-portal/threads/request%2F1/work-plan",
      {
        method: "GET",
        headers: { "X-Portal-Workspace": scope.workspace },
        cache: "no-store",
        signal,
      },
    );
  });
  test("PUT sends only complete plan and expected_revision", async () => {
    const signal = new AbortController().signal;
    mockedFetch.mockResolvedValueOnce(respond(record));
    expect(
      await putWorkPlan({ ...scope, signal, expectedRevision: 0, plan }),
    ).toEqual(record);
    expect(mockedFetch).toHaveBeenCalledWith(
      "/backend/api/client-portal/threads/request%2F1/work-plan",
      {
        method: "PUT",
        headers: {
          "X-Portal-Workspace": scope.workspace,
          "Content-Type": "application/json",
        },
        cache: "no-store",
        signal,
        body: JSON.stringify({ expected_revision: 0, plan }),
      },
    );
  });
  test("preserves 409 detail and never retries", async () => {
    mockedFetch.mockResolvedValueOnce(
      respond(
        { detail: "Internal work plan changed; reload before saving" },
        409,
      ),
    );
    await expect(
      putWorkPlan({ ...scope, expectedRevision: 0, plan }),
    ).rejects.toThrow("Internal work plan changed; reload before saving");
    expect(mockedFetch).toHaveBeenCalledTimes(1);
  });
  test("structured errors are readable and load/save errors distinct", async () => {
    mockedFetch.mockResolvedValueOnce(
      respond({ detail: [{ msg: "bad" }] }, 422),
    );
    await expect(
      putWorkPlan({ ...scope, expectedRevision: 0, plan }),
    ).rejects.toThrow(
      "Could not save the work plan (422). Check the work plan fields.",
    );
    mockedFetch.mockResolvedValueOnce(respond({}, 503));
    await expect(getWorkPlan(scope)).rejects.toThrow(
      "Could not load the work plan (503)",
    );
  });
  test("propagates abort without retry or false success", async () => {
    const error = new DOMException("Aborted", "AbortError");
    mockedFetch.mockRejectedValueOnce(error);
    await expect(getWorkPlan(scope)).rejects.toBe(error);
    expect(mockedFetch).toHaveBeenCalledTimes(1);
  });
  test("rejects malformed, cross-request and wrong-verification responses", async () => {
    for (const body of [
      null,
      { ...record, source: { table: "board_portal", id: "other" } },
      { ...record, verification: "verified" },
      { ...record, revision: 2147483648 },
      { ...record, revision: 1.5 },
      { ...record, plan: { ...plan, next_action: null } },
      { ...record, extra: true },
      { ...record, recorded_at: "2026-10-24T12:00:00" },
    ]) {
      mockedFetch.mockResolvedValueOnce(respond(body));
      await expect(getWorkPlan(scope)).rejects.toThrow("invalid work plan");
    }
    mockedFetch.mockResolvedValueOnce(new Response("not-json"));
    await expect(getWorkPlan(scope)).rejects.toThrow("invalid work plan");
  });
  test("PUT rejects null plan or nonincremented revision", async () => {
    for (const body of [
      { ...record, plan: null },
      { ...record, revision: 0 },
    ]) {
      mockedFetch.mockResolvedValueOnce(respond(body));
      await expect(
        putWorkPlan({ ...scope, expectedRevision: 0, plan }),
      ).rejects.toThrow("did not confirm");
    }
  });
  test("invalid revision or plan never reaches fetch", async () => {
    for (const expectedRevision of [
      -1,
      1.5,
      2147483647,
      NaN,
      "0" as unknown as number,
    ]) {
      await expect(
        putWorkPlan({ ...scope, expectedRevision, plan }),
      ).rejects.toThrow("revision");
    }
    await expect(
      putWorkPlan({
        ...scope,
        expectedRevision: 0,
        plan: { ...plan, outcome: " " },
      }),
    ).rejects.toThrow("Outcome");
    expect(mockedFetch).not.toHaveBeenCalled();
  });
});

describe("work plan validation", () => {
  test("accepts aware dates and Unicode codepoints and maximum revision", async () => {
    expect(() =>
      validateWorkPlan(
        {
          ...plan,
          outcome: "😀".repeat(1000),
          due_at: "2026-10-24T12:00:00+05:30",
        },
        scope.requestId,
      ),
    ).not.toThrow();
    expect(() =>
      validateWorkPlan({ ...plan, outcome: "é".repeat(2000) }, scope.requestId),
    ).not.toThrow();
    mockedFetch.mockResolvedValueOnce(
      respond({ ...record, revision: 2147483647 }),
    );
    await expect(
      putWorkPlan({ ...scope, expectedRevision: 2147483646, plan }),
    ).resolves.toEqual({ ...record, revision: 2147483647 });
  });
  test("enforces text, ID, date, list, enum and strict field bounds", () => {
    const invalid = [
      { outcome: " " },
      { outcome: "a".repeat(2001) },
      { next_action: "" },
      { next_action: "😀".repeat(2001) },
      { assignee_user_id: "" },
      { verifier_user_id: "a".repeat(65) },
      { due_at: "2026-10-24T12:00:00" },
      { due_at: "2026-02-30T12:00:00Z" },
      { dependency_thread_ids: Array.from({ length: 11 }, (_, i) => `r${i}`) },
      { dependency_thread_ids: ["other", "other"] },
      { dependency_thread_ids: [scope.requestId] },
      { status: "done" },
      { evidence_refs: [{ kind: "source", reference: " " }] },
      { evidence_refs: [{ kind: "source", reference: "a".repeat(513) }] },
      {
        evidence_refs: Array.from({ length: 11 }, () => ({
          kind: "delivery",
          reference: "receipt",
        })),
      },
      { evidence_refs: [{ kind: "url", reference: "receipt" }] },
      { extra: true },
      {
        evidence_refs: [{ kind: "source", reference: "receipt", extra: true }],
      },
    ];
    for (const patch of invalid)
      expect(() =>
        validateWorkPlan({ ...plan, ...patch } as WorkPlan, scope.requestId),
      ).toThrow();
  });
  test("counts total UTF-8 bytes instead of JS character length", () => {
    const oversized = {
      ...plan,
      outcome: "界".repeat(1500),
      next_action: "界".repeat(1500),
    };
    expect(JSON.stringify(oversized).length).toBeLessThan(8000);
    expect(() => validateWorkPlan(oversized, scope.requestId)).toThrow(
      "8000 bytes",
    );
  });
  test("reported completion requires a recorded reference", () => {
    expect(() =>
      validateWorkPlan(
        { ...plan, status: "reported_complete" },
        scope.requestId,
      ),
    ).toThrow("requires an evidence reference");
    expect(() =>
      validateWorkPlan(
        {
          ...plan,
          status: "reported_complete",
          evidence_refs: [{ kind: "delivery", reference: "Recorded receipt" }],
        },
        scope.requestId,
      ),
    ).not.toThrow();
  });
});
