import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { QueryObserver } from "@tanstack/react-query";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

import { queryClient } from "@/components/query-client-provider";
import { fetch as apiFetch } from "@/core/api/fetcher";
import { AuthProvider, useAuth } from "@/core/auth/AuthProvider";
import type { User } from "@/core/auth/types";

const router = {
  push: rs.fn(),
  replace: rs.fn(),
  refresh: rs.fn(),
};
const reload = rs.fn<() => void>();

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
  window.history.replaceState(null, "", "/workspace/team");
  reload.mockReset();
  rs.spyOn(window.location, "reload").mockImplementation(reload);
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
  it("keeps mounted query caches until the logout POST completes and skips the login redirect", async () => {
    const pendingLogout = deferred<Response>();
    rs.spyOn(globalThis, "fetch").mockReturnValue(pendingLogout.promise);
    const clear = rs.spyOn(queryClient, "clear");
    const channels = [{ id: "channel-a" }];
    queryClient.setQueryData(["team", "channels"], channels);

    renderAuth(USER_A);
    fireEvent.click(screen.getByRole("button", { name: "Log out" }));

    expect(screen.getByTestId("auth-user").textContent).toBe("signed-out");
    expect(clear).not.toHaveBeenCalled();
    expect(queryClient.getQueryData(["team", "channels"])).toBe(channels);
    expect(router.push).not.toHaveBeenCalled();

    await act(async () => {
      pendingLogout.resolve(new Response(null, { status: 200 }));
      await pendingLogout.promise;
    });

    expect(clear).toHaveBeenCalledTimes(1);
    expect(router.push.mock.calls).toEqual([["/"]]);

    rs.mocked(globalThis.fetch).mockResolvedValue(
      new Response(null, { status: 401 }),
    );
    await expect(apiFetch("/api/threads")).rejects.toThrow();
    expect(window.location.pathname).toBe("/workspace/team");
    expect(router.push.mock.calls).toEqual([["/"]]);
  });

  it("ignores recovery attempts after logout starts", async () => {
    const pendingLogout = deferred<Response>();
    const fetchMock = rs
      .spyOn(globalThis, "fetch")
      .mockReturnValue(pendingLogout.promise);
    renderAuth(USER_A);

    fireEvent.click(screen.getByRole("button", { name: "Log out" }));
    fireEvent.click(screen.getByRole("button", { name: "Apply user B" }));
    fireEvent.click(screen.getByRole("button", { name: "Refresh user" }));

    expect(screen.getByTestId("auth-user").textContent).toBe("signed-out");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/auth/logout", {
      method: "POST",
      credentials: "include",
    });

    await act(async () => {
      pendingLogout.resolve(new Response(null, { status: 200 }));
      await pendingLogout.promise;
    });
  });

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
  it("keeps the confirmed user and cache when /auth/me returns a malformed 200 body", async () => {
    const warn = rs.spyOn(console, "warn").mockImplementation(() => undefined);
    rs.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "gateway response" }), {
        status: 200,
      }),
    );
    renderAuth(USER_A);
    const channels = [{ id: "channel-a" }];
    queryClient.setQueryData(["team", "channels"], channels);

    fireEvent.click(screen.getByRole("button", { name: "Refresh user" }));

    await waitFor(() =>
      expect(screen.getByTestId("auth-loading").textContent).toBe("idle"),
    );
    expect(screen.getByTestId("auth-user").textContent).toBe(USER_A.id);
    expect(queryClient.getQueryData(["team", "channels"])).toBe(channels);
    expect(router.push).not.toHaveBeenCalled();
    expect(warn).toHaveBeenCalledWith(
      "Failed to refresh user: invalid /auth/me response",
    );
  });

  it("uses the live pathname and query when a pending refresh confirms 401", async () => {
    const pendingMe = deferred<Response>();
    rs.spyOn(globalThis, "fetch").mockReturnValue(pendingMe.promise);
    renderAuth(USER_A);
    fireEvent.click(screen.getByRole("button", { name: "Refresh user" }));

    window.history.replaceState(
      null,
      "",
      "/workspace/chats/new?settings=security",
    );
    await act(async () => {
      pendingMe.resolve(new Response(null, { status: 401 }));
      await pendingMe.promise;
    });

    await waitFor(() =>
      expect(screen.getByTestId("auth-user").textContent).toBe("signed-out"),
    );
    expect(new URL(window.location.href).searchParams.get("next")).toBe(
      "/workspace/chats/new?settings=security",
    );
    expect(router.push).not.toHaveBeenCalled();
  });

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
    expect(reload).not.toHaveBeenCalled();
  });

  it("reloads for a changed server identity and fences the previous identity's refresh", async () => {
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
    expect(reload).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("auth-user").textContent).toBe(USER_A.id);
    expect(screen.getByTestId("auth-loading").textContent).toBe("loading");
    expect(queryClient.getQueryData(["team", "channels"])).toEqual([
      { id: "channel-a" },
    ]);

    await act(async () => {
      pendingMe.resolve(responseFor(USER_A));
      await pendingMe.promise;
    });

    expect(reload).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("auth-user").textContent).toBe(USER_A.id);
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
    expect(reload).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("auth-user").textContent).toBe(USER_A.id);

    await act(async () => {
      first.resolve(responseFor(USER_A));
      await first.promise;
    });

    expect(reload).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("auth-user").textContent).toBe(USER_A.id);
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
    expect(reload).toHaveBeenCalledTimes(1);
    await act(async () => {
      pendingMe.resolve(responseFor(USER_A));
      await pendingMe.promise;
    });

    expect(screen.getByTestId("auth-user").textContent).toBe(USER_A.id);
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("reloads without detaching a mounted query or publishing the next account", async () => {
    const pending = deferred<string[]>();
    queryClient.setQueryData(["account-screen"], ["account-a"]);
    const observer = new QueryObserver(queryClient, {
      queryKey: ["account-screen"],
      queryFn: () => pending.promise,
    });
    const unsubscribe = observer.subscribe(() => undefined);
    const query = queryClient
      .getQueryCache()
      .find({ queryKey: ["account-screen"] });
    renderAuth(USER_A);

    fireEvent.click(screen.getByRole("button", { name: "Apply user B" }));

    expect(reload).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("auth-user").textContent).toBe(USER_A.id);
    expect(
      queryClient.getQueryCache().find({ queryKey: ["account-screen"] }),
    ).toBe(query);
    pending.resolve(["settled-read"]);
    await waitFor(() =>
      expect(observer.getCurrentResult().data).toEqual(["settled-read"]),
    );
    unsubscribe();
  });
});
