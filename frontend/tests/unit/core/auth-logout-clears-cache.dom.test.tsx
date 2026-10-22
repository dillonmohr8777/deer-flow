import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

import { queryClient } from "@/components/query-client-provider";
import {
  AuthProvider,
  useAuth,
  useRequireAuth,
} from "@/core/auth/AuthProvider";
import type { User } from "@/core/auth/types";

const router = {
  push: rs.fn(),
  replace: rs.fn(),
  refresh: rs.fn(),
};

// Same seams as gateway-offline-banner.dom.test.tsx: an inert router, and the
// SPA branch of logout (the one that soft-navigates and keeps this tab's
// module-level query cache alive).
rs.mock("next/navigation", () => ({
  useRouter: () => router,
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

beforeEach(() => {
  router.push.mockClear();
  router.replace.mockClear();
  router.refresh.mockClear();
});

const USER_A: User = {
  id: "user-a",
  email: "a@example.test",
  system_role: "user",
  needs_setup: false,
};

const USER_B: User = {
  id: "user-b",
  email: "b@example.test",
  system_role: "admin",
  needs_setup: false,
};

function responseFor(user: User): Response {
  return new Response(JSON.stringify(user), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function LogoutButton() {
  const { logout } = useAuth();
  return (
    <button type="button" onClick={() => void logout()}>
      Log out
    </button>
  );
}

function AuthControls() {
  const auth = useAuth();
  useRequireAuth();

  return (
    <div>
      <output data-testid="auth-user">{auth.user?.id ?? "signed-out"}</output>
      <output data-testid="auth-loading">
        {auth.isLoading ? "loading" : "idle"}
      </output>
      <button type="button" onClick={() => void auth.refreshUser()}>
        Refresh user
      </button>
      <button type="button" onClick={() => auth.applyUser(USER_B)}>
        Apply user B
      </button>
      <button type="button" onClick={() => void auth.logout()}>
        Log out
      </button>
    </div>
  );
}

function renderAuth(initialUser: User | null) {
  return render(
    <AuthProvider initialUser={initialUser}>
      <AuthControls />
    </AuthProvider>,
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

  it("does not restore a user from a refresh that began before logout", async () => {
    const pendingMe = deferred<Response>();
    rs.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url =
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.toString()
            : input.url;
      if (url === "/api/v1/auth/me") return pendingMe.promise;
      return Promise.resolve(
        new Response(JSON.stringify({ message: "Successfully logged out" }), {
          status: 200,
        }),
      );
    });
    queryClient.setQueryData(["team", "channels"], [{ id: "c1" }]);

    renderAuth(USER_A);
    fireEvent.click(screen.getByRole("button", { name: "Refresh user" }));
    await waitFor(() =>
      expect(screen.getByTestId("auth-loading").textContent).toBe("loading"),
    );

    fireEvent.click(screen.getByRole("button", { name: "Log out" }));
    await waitFor(() =>
      expect(queryClient.getQueryData(["team", "channels"])).toBeUndefined(),
    );

    await act(async () => {
      pendingMe.resolve(responseFor(USER_A));
      await pendingMe.promise;
    });

    expect(screen.getByTestId("auth-user").textContent).toBe("signed-out");
    expect(queryClient.getQueryData(["team", "channels"])).toBeUndefined();
  });
});

describe("refreshUser", () => {
  it("keeps the last confirmed user when /auth/me fails at the network layer", async () => {
    rs.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("offline"));
    rs.spyOn(console, "error").mockImplementation(() => undefined);

    renderAuth(USER_A);
    fireEvent.click(screen.getByRole("button", { name: "Refresh user" }));

    await waitFor(() =>
      expect(screen.getByTestId("auth-loading").textContent).toBe("idle"),
    );
    expect(screen.getByTestId("auth-user").textContent).toBe(USER_A.id);
    expect(router.push).not.toHaveBeenCalled();
  });

  it("retains cached data when /auth/me confirms the same user", async () => {
    rs.spyOn(globalThis, "fetch").mockResolvedValue(responseFor(USER_A));

    renderAuth(USER_A);
    const channels = [{ id: "channel-a" }];
    queryClient.setQueryData(["team", "channels"], channels);

    fireEvent.click(screen.getByRole("button", { name: "Refresh user" }));

    await waitFor(() =>
      expect(screen.getByTestId("auth-loading").textContent).toBe("idle"),
    );
    expect(queryClient.getQueryData(["team", "channels"])).toBe(channels);
  });

  it("uses a replaced server user and ignores a refresh from the previous identity", async () => {
    const pendingMe = deferred<Response>();
    rs.spyOn(globalThis, "fetch").mockImplementation(() => pendingMe.promise);

    const view = renderAuth(USER_A);
    queryClient.setQueryData(["team", "channels"], [{ id: "channel-a" }]);
    queryClient.setQueryData(["academy", "courses"], [{ id: "course-a" }]);
    queryClient.setQueryData(["threads", "inbox"], [{ id: "thread-a" }]);
    fireEvent.click(screen.getByRole("button", { name: "Refresh user" }));
    await waitFor(() =>
      expect(screen.getByTestId("auth-loading").textContent).toBe("loading"),
    );

    view.rerender(
      <AuthProvider initialUser={USER_B}>
        <AuthControls />
      </AuthProvider>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("auth-user").textContent).toBe(USER_B.id),
    );
    expect(queryClient.getQueryData(["team", "channels"])).toBeUndefined();
    expect(queryClient.getQueryData(["academy", "courses"])).toBeUndefined();
    expect(queryClient.getQueryData(["threads", "inbox"])).toBeUndefined();

    await act(async () => {
      pendingMe.resolve(responseFor(USER_A));
      await pendingMe.promise;
    });

    expect(screen.getByTestId("auth-user").textContent).toBe(USER_B.id);
    expect(screen.getByTestId("auth-loading").textContent).toBe("idle");
  });

  it("ignores older responses when refresh requests finish out of order", async () => {
    const first = deferred<Response>();
    const second = deferred<Response>();
    let requestCount = 0;
    const fetchMock = rs
      .spyOn(globalThis, "fetch")
      .mockImplementation(() =>
        requestCount++ === 0 ? first.promise : second.promise,
      );

    renderAuth(USER_A);
    queryClient.setQueryData(["team", "channels"], [{ id: "channel-a" }]);
    fireEvent.click(screen.getByRole("button", { name: "Refresh user" }));
    fireEvent.click(screen.getByRole("button", { name: "Refresh user" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));

    await act(async () => {
      second.resolve(responseFor(USER_B));
      await second.promise;
    });
    await waitFor(() =>
      expect(screen.getByTestId("auth-user").textContent).toBe(USER_B.id),
    );
    expect(queryClient.getQueryData(["team", "channels"])).toBeUndefined();

    await act(async () => {
      first.resolve(responseFor(USER_A));
      await first.promise;
    });

    expect(screen.getByTestId("auth-user").textContent).toBe(USER_B.id);
    expect(screen.getByTestId("auth-loading").textContent).toBe("idle");
  });

  it("fences a pending refresh when an authoritative user is applied", async () => {
    const pendingMe = deferred<Response>();
    rs.spyOn(globalThis, "fetch").mockImplementation(() => pendingMe.promise);

    renderAuth(USER_A);
    queryClient.setQueryData(["team", "channels"], [{ id: "channel-a" }]);
    fireEvent.click(screen.getByRole("button", { name: "Refresh user" }));
    await waitFor(() =>
      expect(screen.getByTestId("auth-loading").textContent).toBe("loading"),
    );

    fireEvent.click(screen.getByRole("button", { name: "Apply user B" }));
    expect(queryClient.getQueryData(["team", "channels"])).toBeUndefined();
    await act(async () => {
      pendingMe.resolve(responseFor(USER_A));
      await pendingMe.promise;
    });

    expect(screen.getByTestId("auth-user").textContent).toBe(USER_B.id);
    expect(screen.getByTestId("auth-loading").textContent).toBe("idle");
  });
});
