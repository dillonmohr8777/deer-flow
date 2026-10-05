import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";

import {
  getWorkflowWorkspaceProjection,
  prepareJevboxEvidence,
} from "@/core/workflows/api";

rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "" }));
rs.mock("@/core/static-mode", () => ({ isStaticWebsiteOnly: () => false }));

const network = rs.fn<typeof globalThis.fetch>();
let originalFetch: typeof globalThis.fetch;

beforeEach(() => {
  originalFetch = globalThis.fetch;
  globalThis.fetch = network;
  document.cookie = "csrf_token=fixture-csrf; path=/";
  network.mockResolvedValue(
    new Response(JSON.stringify({ detail: "workspace_scope_changed" }), {
      status: 409,
      headers: { "Content-Type": "application/json" },
    }),
  );
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  document.cookie = "csrf_token=; max-age=0; path=/";
  network.mockReset();
});

describe("Jevbox preparation transport", () => {
  it("accepts the backend workspace name bound in Unicode code points", async () => {
    network.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          active_workspace_id: "workspace-one",
          workspaces: [
            { id: "workspace-one", name: "🧪".repeat(256), role: "owner" },
          ],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    await expect(getWorkflowWorkspaceProjection()).resolves.toEqual({
      activeWorkspaceId: "workspace-one",
    });
  });

  it("posts the exact original File bytes through the authenticated CSRF fetcher without retaining them", async () => {
    const bytes = new TextEncoder().encode(
      '{"reviewed": true, "keep spacing": "exact"}\n',
    );
    const file = new File([bytes], "reviewed.json", {
      type: "application/json",
    });
    await expect(
      prepareJevboxEvidence(file, "scope-one", {
        ownerId: "owner-one",
        workspaceId: "workspace-one",
      }),
    ).rejects.toMatchObject({ message: "workspace_scope_changed" });

    expect(network).toHaveBeenCalledTimes(1);
    const [url, init] = network.mock.calls[0]!;
    expect(url).toBe("/api/workflows/jevbox/prepare");
    expect(init?.method).toBe("POST");
    expect(init?.body).toBe(file);
    expect(init?.cache).toBe("no-store");
    expect(init?.credentials).toBe("include");
    const headers = new Headers(init?.headers);
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(headers.get("X-Expected-Workflow-Scope")).toBe("scope-one");
    expect(headers.get("X-CSRF-Token")).toBe("fixture-csrf");
    expect(await new Response(init?.body).arrayBuffer()).toEqual(
      bytes.buffer,
    );
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });
});
