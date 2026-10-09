import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";

// Review coverage gap (f134): every existing test stubs `AgentRoomAccessDeniedError`
// with a plain class, so nothing ever proved `fetchAgentRoomEnabled` actually
// throws *that* class only for 403/404, nor that the hook's sticky admission
// (hooks.ts) treats it as a real revoke. This file uses the real `api.ts`
// module -- only the network layer is mocked -- to close that gap.
rs.mock("next/navigation", () => ({
  useRouter: () => ({ push: rs.fn(), replace: rs.fn() }),
  usePathname: () => "/workspace/desk/agent-room",
}));
rs.mock("@/core/static-mode", () => ({ isStaticWebsiteOnly: () => false }));
rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "" }));

import { useAgentRoomAccess } from "@/core/agent-room/hooks";
import { AUTH_DISABLED_USER } from "@/core/auth/auth-disabled-user";
import { AuthProvider } from "@/core/auth/AuthProvider";

const OWNER_A = { ...AUTH_DISABLED_USER, id: "owner-A" };

function mount() {
  const cache = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <AuthProvider initialUser={OWNER_A}>
      <QueryClientProvider client={cache}>{children}</QueryClientProvider>
    </AuthProvider>
  );
  return {
    cache,
    ...renderHook(() => useAgentRoomAccess(), { wrapper: Wrapper }),
  };
}

const network = rs.fn<typeof globalThis.fetch>();
let originalFetch: typeof globalThis.fetch;
beforeEach(() => {
  originalFetch = globalThis.fetch;
  globalThis.fetch = network;
});
afterEach(() => {
  globalThis.fetch = originalFetch;
  network.mockReset();
});

function featuresResponse(status: number) {
  return new Response(
    JSON.stringify({ agents_api: { enabled: true }, desk: { enabled: true } }),
    { status },
  );
}

describe("real access-denial classification revokes admission", () => {
  it("a 403 discovery response revokes an already-admitted owner", async () => {
    network
      .mockResolvedValueOnce(featuresResponse(200))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: "no" }), { status: 403 }),
      );
    const view = mount();
    await waitFor(() => expect(view.result.current.enabled).toBe(true));

    await view.cache.refetchQueries({
      queryKey: ["agent-room", "access", "owner-A"],
    });

    await waitFor(() => expect(view.result.current.enabled).toBe(false));
  });

  it("a 404 discovery response revokes an already-admitted owner", async () => {
    network
      .mockResolvedValueOnce(featuresResponse(200))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: "no" }), { status: 404 }),
      );
    const view = mount();
    await waitFor(() => expect(view.result.current.enabled).toBe(true));

    await view.cache.refetchQueries({
      queryKey: ["agent-room", "access", "owner-A"],
    });

    await waitFor(() => expect(view.result.current.enabled).toBe(false));
  });

  it("a 500 discovery response does not revoke an already-admitted owner", async () => {
    network
      .mockResolvedValueOnce(featuresResponse(200))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: "no" }), { status: 500 }),
      );
    const view = mount();
    await waitFor(() => expect(view.result.current.enabled).toBe(true));

    await view.cache
      .refetchQueries({ queryKey: ["agent-room", "access", "owner-A"] })
      .catch(() => {
        // A 500 rejects the fetch; that rejection is expected and is the point of the test.
      });
    await waitFor(() =>
      expect(
        view.cache.getQueryState(["agent-room", "access", "owner-A"])
          ?.fetchStatus,
      ).toBe("idle"),
    );

    expect(view.result.current.enabled).toBe(true);
  });
});
