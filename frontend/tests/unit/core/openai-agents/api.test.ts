import { beforeEach, describe, expect, it, rs } from "@rstest/core";

rs.mock("@/core/api/fetcher", () => ({ fetch: rs.fn() }));
rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "" }));

import { fetch } from "@/core/api/fetcher";
import {
  downloadAgentArtifact,
  getAgentSession,
  getOpenAIAgentStatus,
  submitAgentInput,
} from "@/core/openai-agents/api";

const mockedFetch = rs.mocked(fetch);
beforeEach(() => {
  mockedFetch.mockReset();
});

describe("OpenAI session requests", () => {
  it("pins the actor on status and rejects a changed cookie scope instead of rendering success", async () => {
    mockedFetch.mockImplementation(
      async () =>
        new Response('{"detail":"workspace_scope_changed"}', { status: 409 }),
    );
    await expect(getOpenAIAgentStatus("owner-one")).rejects.toThrow(
      "workspace_scope_changed",
    );
    expect(mockedFetch).toHaveBeenCalledWith("/api/openai-agents/status", {
      signal: undefined,
      cache: "no-store",
      headers: { "X-Expected-User-Id": "owner-one" },
    });
    await expect(getAgentSession("private", "old-workspace")).rejects.toThrow(
      "workspace_scope_changed",
    );
  });
  it("downloads artifacts through the Gateway with the scope header and rejects login HTML", async () => {
    mockedFetch.mockResolvedValue(
      new Response("login", { headers: { "Content-Type": "text/html" } }),
    );
    await expect(
      downloadAgentArtifact("local/session", "generated/file", "scope-one"),
    ).rejects.toThrow("did not return an agent file");
    expect(mockedFetch).toHaveBeenCalledWith(
      "/api/openai-agents/sessions/local%2Fsession/artifacts/generated%2Ffile/content",
      {
        cache: "no-store",
        signal: undefined,
        headers: { "X-Expected-Agent-Scope": "scope-one" },
      },
    );
  });
  it("preserves the caller's paid-work receipt and encodes local session identifiers", async () => {
    mockedFetch.mockResolvedValue(
      new Response("{}", { headers: { "Content-Type": "application/json" } }),
    );
    await submitAgentInput(
      "Bounded task",
      "stable-receipt",
      "scope-one",
      "private/session",
    );
    expect(mockedFetch).toHaveBeenCalledWith(
      "/api/openai-agents/sessions/private%2Fsession/messages",
      expect.objectContaining({
        method: "POST",
        cache: "no-store",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": "stable-receipt",
          "X-Expected-Agent-Scope": "scope-one",
        },
        body: JSON.stringify({ input: "Bounded task" }),
      }),
    );
  });
  it("aborts stale owner reads and never turns errors into an empty result", async () => {
    const controller = new AbortController();
    mockedFetch.mockResolvedValue(
      new Response('{"detail":"not_found"}', { status: 404 }),
    );
    await expect(
      getAgentSession("private/session", "scope-one", controller.signal),
    ).rejects.toThrow("not_found");
    expect(mockedFetch).toHaveBeenCalledWith(
      "/api/openai-agents/sessions/private%2Fsession",
      {
        signal: controller.signal,
        cache: "no-store",
        headers: { "X-Expected-Agent-Scope": "scope-one" },
      },
    );
  });
});
