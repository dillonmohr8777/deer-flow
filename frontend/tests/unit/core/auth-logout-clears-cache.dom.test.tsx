import { afterEach, describe, expect, it, rs } from "@rstest/core";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

import { queryClient } from "@/components/query-client-provider";
import { AuthProvider, useAuth } from "@/core/auth/AuthProvider";

// Same seams as gateway-offline-banner.dom.test.tsx: an inert router, and the
// SPA branch of logout (the one that soft-navigates and keeps this tab's
// module-level query cache alive).
rs.mock("next/navigation", () => ({
  useRouter: () => ({ push: rs.fn(), replace: rs.fn(), refresh: rs.fn() }),
  usePathname: () => "/workspace/team",
}));
rs.mock("@/core/static-mode", () => ({
  isStaticWebsiteOnly: () => false,
}));

afterEach(() => {
  rs.restoreAllMocks();
  queryClient.clear();
  cleanup();
});

function LogoutButton() {
  const { logout } = useAuth();
  return (
    <button type="button" onClick={() => void logout()}>
      Log out
    </button>
  );
}

describe("logout", () => {
  it("drops cached responses so the next person on this tab can't see them", async () => {
    rs.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ message: "Successfully logged out" }), {
        status: 200,
      }),
    );
    // Staff-only data a Momentum staffer had loaded before logging out.
    queryClient.setQueryData(["team", "channels"], [{ id: "c1" }]);
    queryClient.setQueryData(["features", "momentum_internal"], true);

    render(
      <AuthProvider initialUser={null}>
        <LogoutButton />
      </AuthProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Log out" }));

    await waitFor(() => {
      expect(queryClient.getQueryData(["team", "channels"])).toBeUndefined();
    });
    expect(
      queryClient.getQueryData(["features", "momentum_internal"]),
    ).toBeUndefined();
  });
});
