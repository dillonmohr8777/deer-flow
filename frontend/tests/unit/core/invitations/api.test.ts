import { beforeEach, describe, expect, it, rs } from "@rstest/core";

const mocks = rs.hoisted(() => ({ fetch: rs.fn() }));

rs.mock("@/core/api/fetcher", () => ({ fetch: mocks.fetch }));

import {
  buildInviteLink,
  classifyInviteFailure,
  createInvitation,
  defaultInviteWorkspaceId,
  INVITE_ROLES,
  InviteRequestError,
  inviteTargets,
  loadInviteWorkspaces,
} from "@/core/invitations/api";

const FROZEN_DETAIL =
  "Workspace invitations are paused while workspace isolation is upgraded. Existing members keep their access.";

function response(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

beforeEach(() => {
  mocks.fetch.mockReset();
});

describe("INVITE_ROLES", () => {
  it("offers member, admin and client with member first", () => {
    expect([...INVITE_ROLES]).toEqual(["member", "admin", "client"]);
  });
});

describe("buildInviteLink", () => {
  it("puts the token in the URL fragment, never the query", () => {
    const link = buildInviteLink("https://momo.example.com", "abc_DEF-123");
    expect(link).toBe("https://momo.example.com/invite#token=abc_DEF-123");
    expect(new URL(link).search).toBe("");
    expect(new URL(link).hash).toBe("#token=abc_DEF-123");
  });

  it("drops a trailing slash on the origin", () => {
    expect(buildInviteLink("https://momo.example.com/", "t")).toBe(
      "https://momo.example.com/invite#token=t",
    );
  });
});

describe("inviteTargets", () => {
  it("keeps only workspaces where the caller is owner or admin", () => {
    const targets = inviteTargets([
      { id: "a", name: "A", role: "owner" },
      { id: "b", name: "B", role: "member" },
      { id: "c", name: "C", role: "admin" },
      { id: "d", name: "D", role: "client" },
    ]);
    expect(targets.map((w) => w.id)).toEqual(["a", "c"]);
  });

  it("returns nothing when there are no shared workspaces", () => {
    expect(inviteTargets([])).toEqual([]);
  });
});

describe("defaultInviteWorkspaceId", () => {
  const targets = [
    { id: "a", name: "A", role: "owner" },
    { id: "c", name: "C", role: "admin" },
  ];

  it("prefers the active workspace when it is eligible", () => {
    expect(defaultInviteWorkspaceId(targets, "c")).toBe("c");
  });

  it("falls back to the first eligible workspace", () => {
    expect(defaultInviteWorkspaceId(targets, "zzz")).toBe("a");
    expect(defaultInviteWorkspaceId(targets, null)).toBe("a");
  });

  it("returns an empty string when nothing is eligible", () => {
    expect(defaultInviteWorkspaceId([], "a")).toBe("");
  });
});

describe("classifyInviteFailure", () => {
  it("recognises the frozen 403", () => {
    expect(classifyInviteFailure(403, FROZEN_DETAIL)).toBe("frozen");
  });

  it("treats any other 403 as a role problem", () => {
    expect(
      classifyInviteFailure(
        403,
        "Only an active workspace owner or admin can invite members",
      ),
    ).toBe("forbidden");
    expect(classifyInviteFailure(403, undefined)).toBe("forbidden");
  });

  it("maps 409 to conflict", () => {
    expect(classifyInviteFailure(409, "already exists")).toBe("conflict");
  });

  it("maps a 422 on the email field to invalid_email", () => {
    expect(
      classifyInviteFailure(422, [
        { loc: ["body", "email"], msg: "bad", type: "value_error" },
      ]),
    ).toBe("invalid_email");
  });

  it("maps other 422s to invalid", () => {
    expect(
      classifyInviteFailure(422, [
        { loc: ["body", "role"], msg: "bad", type: "literal_error" },
      ]),
    ).toBe("invalid");
    expect(classifyInviteFailure(422, undefined)).toBe("invalid");
  });

  it("maps 503 to unavailable and anything else to unknown", () => {
    expect(classifyInviteFailure(503, "persistence unavailable")).toBe(
      "unavailable",
    );
    expect(classifyInviteFailure(500, "boom")).toBe("unknown");
  });
});

describe("loadInviteWorkspaces", () => {
  it("returns the workspace list and active id", async () => {
    mocks.fetch.mockResolvedValue(
      response(200, {
        workspaces: [{ id: "a", name: "Momentum", role: "owner" }],
        active_workspace_id: "a",
      }),
    );
    const result = await loadInviteWorkspaces();
    expect(result.active_workspace_id).toBe("a");
    expect(result.workspaces).toHaveLength(1);
    expect(mocks.fetch.mock.calls[0]![0]).toContain("/api/workspaces");
  });

  it("throws when the request fails", async () => {
    mocks.fetch.mockResolvedValue(response(500, { detail: "nope" }));
    await expect(loadInviteWorkspaces()).rejects.toThrow();
  });
});

describe("createInvitation", () => {
  it("POSTs organization_id, email and role as JSON", async () => {
    mocks.fetch.mockResolvedValue(
      response(201, {
        id: "inv1",
        token: "tok",
        expires_at: "2026-10-01T00:00:00Z",
        email: "new@example.com",
        workspace_name: "Momentum",
      }),
    );
    const created = await createInvitation({
      organizationId: "org1",
      email: "new@example.com",
      role: "admin",
    });
    expect(created.token).toBe("tok");
    const [url, init] = mocks.fetch.mock.calls[0]! as [string, RequestInit];
    expect(url).toContain("/api/v1/auth/invitations");
    expect(url).not.toContain("?");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      organization_id: "org1",
      email: "new@example.com",
      role: "admin",
    });
  });

  it("throws a classified error carrying no token on the frozen 403", async () => {
    mocks.fetch.mockResolvedValue(response(403, { detail: FROZEN_DETAIL }));
    const error = await createInvitation({
      organizationId: "org1",
      email: "new@example.com",
      role: "member",
    }).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(InviteRequestError);
    expect((error as InviteRequestError).kind).toBe("frozen");
  });

  it("classifies a 422 email error", async () => {
    mocks.fetch.mockResolvedValue(
      response(422, {
        detail: [{ loc: ["body", "email"], msg: "bad", type: "value_error" }],
      }),
    );
    const error = await createInvitation({
      organizationId: "org1",
      email: "nope",
      role: "member",
    }).catch((e: unknown) => e);
    expect((error as InviteRequestError).kind).toBe("invalid_email");
  });

  it("classifies a thrown fetch as a network error", async () => {
    mocks.fetch.mockRejectedValue(new TypeError("Failed to fetch"));
    const error = await createInvitation({
      organizationId: "org1",
      email: "new@example.com",
      role: "member",
    }).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(InviteRequestError);
    expect((error as InviteRequestError).kind).toBe("network");
  });
});
