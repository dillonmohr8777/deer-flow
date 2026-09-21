import { afterEach, describe, expect, it, rs } from "@rstest/core";

import {
  readWorkspaceBranding,
  resetWorkspaceBranding,
  saveWorkspaceBranding,
  WorkspaceBrandingError,
} from "@/core/workspaces/api";

const { request } = rs.hoisted(() => ({ request: rs.fn() }));
rs.mock("@/core/api/fetcher", () => ({ fetch: request }));
rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "" }));
const branding = {
  workspace_id: "org/a",
  workspace_name: "Client",
  brand_name: null,
  logo: null,
  treatment: "paper",
  version: 2,
  updated_at: null,
  can_edit: true,
};
afterEach(() => {
  request.mockReset();
});

describe("shared branding contract", () => {
  it("scopes reads and conditional writes/reset to the workspace, with no shared motion field", async () => {
    request.mockImplementation(() =>
      Promise.resolve(new Response(JSON.stringify(branding), { status: 200 })),
    );
    await readWorkspaceBranding("org/a");
    expect(request.mock.calls[0]![0]).toBe("/api/workspaces/org%2Fa/branding");
    await saveWorkspaceBranding(
      "org/a",
      { brand_name: "Client", logo: null, treatment: "paper" },
      1,
    );
    const init = request.mock.calls[1]![1] as RequestInit;
    expect(JSON.parse(init.body as string)).toEqual({
      brand_name: "Client",
      logo: null,
      treatment: "paper",
      expected_version: 1,
    });
    await resetWorkspaceBranding("org/a", 2);
    expect(request.mock.calls[2]![0]).toBe(
      "/api/workspaces/org%2Fa/branding?expected_version=2",
    );
    expect(request.mock.calls[2]![1]).toEqual({ method: "DELETE" });
  });
  it("rejects unsafe or cross-workspace responses and preserves permission/conflict status", async () => {
    request.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          ...branding,
          logo: "https://example.com/foreign.svg",
        }),
      ),
    );
    await expect(readWorkspaceBranding("org/a")).rejects.toThrow();
    request.mockResolvedValueOnce(
      new Response(JSON.stringify({ ...branding, workspace_id: "other" })),
    );
    await expect(readWorkspaceBranding("org/a")).rejects.toThrow(
      "did not match",
    );
    for (const status of [403, 412]) {
      request.mockResolvedValueOnce(new Response("{}", { status }));
      try {
        await resetWorkspaceBranding("org/a", 2);
        throw new Error("Expected rejection");
      } catch (error) {
        expect(error).toBeInstanceOf(WorkspaceBrandingError);
        expect((error as WorkspaceBrandingError).status).toBe(status);
      }
    }
  });
});
