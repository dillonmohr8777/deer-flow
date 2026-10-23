import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";

import {
  fetchAgentRoomEnabled,
  listAgentRoomMessages,
  postAgentRoomMessage,
} from "@/core/agent-room/api";
import {
  useAgentRoomAccess,
  useAgentRoomMessages,
  usePostAgentRoomMessage,
} from "@/core/agent-room/hooks";
import type { AgentRoomMessage } from "@/core/agent-room/types";
import { AUTH_DISABLED_USER } from "@/core/auth/auth-disabled-user";
import { AuthProvider, useAuth } from "@/core/auth/AuthProvider";
import type { User } from "@/core/auth/types";
import { UserPreferencesBoundary } from "@/core/settings/user-preferences-boundary";

rs.mock("next/navigation", () => ({
  useRouter: () => ({ push: rs.fn(), replace: rs.fn() }),
  usePathname: () => "/workspace/desk/agent-room",
}));
rs.mock("@/core/static-mode", () => ({ isStaticWebsiteOnly: () => false }));
rs.mock("@/core/settings/user-preferences", () => ({
  startUserPreferences: () => rs.fn(),
}));
rs.mock("@/core/agent-room/api", () => ({
  AGENT_ROOM_MESSAGES_QUERY_KEY: ["agent-room", "messages"],
  AgentRoomAccessDeniedError: class AgentRoomAccessDeniedError extends Error {},
  fetchAgentRoomEnabled: rs.fn(),
  listAgentRoomMessages: rs.fn(),
  postAgentRoomMessage: rs.fn(),
}));

const OWNER_A: User = { ...AUTH_DISABLED_USER, id: "owner-A" };
const OWNER_B: User = { ...AUTH_DISABLED_USER, id: "owner-B" };
const INPUT = {
  body: "Owner A instruction",
  message_type: "instruction" as const,
};
const message = (owner: string): AgentRoomMessage => ({
  id: `private-${owner}`,
  user_id: owner,
  author_kind: "owner",
  agent_id: null,
  agent_role: "",
  message_type: "instruction",
  body: `PRIVATE ${owner} EVIDENCE`,
  run_id: null,
  created_at: "2026-09-29T14:00:00Z",
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function mount(
  initialUser: User | null = OWNER_A,
  boundary = true,
  prepareCache?: (cache: QueryClient) => void,
) {
  const cache = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  prepareCache?.(cache);
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <AuthProvider initialUser={initialUser}>
      <QueryClientProvider client={cache}>
        {boundary ? (
          <UserPreferencesBoundary>{children}</UserPreferencesBoundary>
        ) : (
          children
        )}
      </QueryClientProvider>
    </AuthProvider>
  );
  const view = renderHook(
    () => ({
      auth: useAuth(),
      access: useAgentRoomAccess(),
      room: useAgentRoomMessages(),
      post: usePostAgentRoomMessage(),
    }),
    { wrapper: Wrapper },
  );
  return { ...view, cache };
}

function reloadTo(view: ReturnType<typeof mount>, user: User, boundary = true) {
  const reload = rs
    .spyOn(window.location, "reload")
    .mockImplementation(() => undefined);
  reload.mockClear();
  act(() => view.result.current.auth.applyUser(user));
  expect(reload).toHaveBeenCalledTimes(1);
  view.unmount();
  return mount(user, boundary);
}

beforeEach(() => {
  rs.mocked(fetchAgentRoomEnabled).mockResolvedValue(true);
  rs.mocked(listAgentRoomMessages).mockResolvedValue([]);
  rs.mocked(postAgentRoomMessage).mockResolvedValue(message("owner-A"));
});
afterEach(() => {
  cleanup();
  rs.resetAllMocks();
  rs.restoreAllMocks();
});

describe("private Agent Room account isolation", () => {
  it("hides owner A cache while B's read is pending after a full page identity reload", async () => {
    rs.mocked(listAgentRoomMessages).mockResolvedValueOnce([
      message("owner-A"),
    ]);
    const pendingB = deferred<AgentRoomMessage[]>();
    rs.mocked(listAgentRoomMessages).mockImplementation(() => pendingB.promise);
    const viewA = mount();
    await waitFor(() =>
      expect(viewA.result.current.room.data?.[0]?.user_id).toBe("owner-A"),
    );
    const viewB = reloadTo(viewA, OWNER_B);
    await waitFor(() => expect(listAgentRoomMessages).toHaveBeenCalledTimes(2));
    expect(viewB.result.current.room.data).toBeUndefined();
    expect(
      viewB.cache.getQueryData(["agent-room", "messages", "owner-A"]),
    ).toBeUndefined();
    pendingB.resolve([message("owner-B")]);
    await waitFor(() =>
      expect(viewB.result.current.room.data?.[0]?.user_id).toBe("owner-B"),
    );
    expect(
      viewA.cache.getQueryData(["agent-room", "messages", "owner-A"]),
    ).toEqual([message("owner-A")]);
  });

  it("does not read or project a saved owner cache before that owner's private gate confirms", async () => {
    const gate = deferred<boolean>();
    rs.mocked(fetchAgentRoomEnabled).mockImplementation(() => gate.promise);
    const view = mount();
    view.cache.setQueryData(
      ["agent-room", "messages", "owner-A"],
      [message("owner-A")],
    );
    expect(view.result.current.room.data).toBeUndefined();
    expect(listAgentRoomMessages).not.toHaveBeenCalled();
    gate.resolve(false);
    await waitFor(() =>
      expect(rs.mocked(fetchAgentRoomEnabled)).toHaveBeenCalled(),
    );
    expect(view.result.current.room.data).toBeUndefined();
    expect(listAgentRoomMessages).not.toHaveBeenCalled();
  });

  it("does not admit reads, cached projection or posts from a prior affirmative access cache while fresh discovery is pending", async () => {
    const gate = deferred<boolean>();
    rs.mocked(fetchAgentRoomEnabled).mockImplementation(() => gate.promise);
    const view = mount(OWNER_A, true, (cache) => {
      cache.setQueryData(["agent-room", "access", "owner-A"], true);
      cache.setQueryData(
        ["agent-room", "messages", "owner-A"],
        [message("owner-A")],
      );
    });
    await waitFor(() => expect(fetchAgentRoomEnabled).toHaveBeenCalled());
    expect(view.result.current.room.data).toBeUndefined();
    expect(listAgentRoomMessages).not.toHaveBeenCalled();
    await expect(view.result.current.post.mutateAsync(INPUT)).rejects.toThrow(
      "posting is unavailable",
    );
    expect(postAgentRoomMessage).not.toHaveBeenCalled();
    gate.resolve(false);
    await waitFor(() =>
      expect(view.cache.getQueryData(["agent-room", "access", "owner-A"])).toBe(
        false,
      ),
    );
    expect(view.result.current.room.data).toBeUndefined();
    expect(listAgentRoomMessages).not.toHaveBeenCalled();
  });

  it("refuses a prior affirmative cache after the required fresh discovery rejects", async () => {
    rs.mocked(fetchAgentRoomEnabled).mockRejectedValue(
      new Error("Private discovery unavailable"),
    );
    const view = mount(OWNER_A, true, (cache) => {
      cache.setQueryData(["agent-room", "access", "owner-A"], true);
      cache.setQueryData(
        ["agent-room", "messages", "owner-A"],
        [message("owner-A")],
      );
    });
    await waitFor(() =>
      expect(
        view.cache.getQueryState(["agent-room", "access", "owner-A"])?.status,
      ).toBe("error"),
    );
    expect(view.result.current.room.data).toBeUndefined();
    expect(listAgentRoomMessages).not.toHaveBeenCalled();
    await expect(view.result.current.post.mutateAsync(INPUT)).rejects.toThrow(
      "posting is unavailable",
    );
    expect(postAgentRoomMessage).not.toHaveBeenCalled();
  });

  it("cancels and fences a late owner A read across a full page identity reload", async () => {
    const pendingA = deferred<AgentRoomMessage[]>();
    rs.mocked(listAgentRoomMessages)
      .mockImplementationOnce(() => pendingA.promise)
      .mockResolvedValue([message("owner-B")]);
    const viewA = mount();
    await waitFor(() => expect(listAgentRoomMessages).toHaveBeenCalledTimes(1));
    const signal = rs.mocked(listAgentRoomMessages).mock.calls[0]?.[1];
    const viewB = reloadTo(viewA, OWNER_B);
    await waitFor(() =>
      expect(viewB.result.current.room.data?.[0]?.user_id).toBe("owner-B"),
    );
    expect(signal?.aborted).toBe(true);
    pendingA.resolve([message("owner-A")]);
    await act(async () => {
      await pendingA.promise;
    });
    expect(viewB.result.current.room.data).toEqual([message("owner-B")]);
    expect(
      viewA.cache.getQueryData(["agent-room", "messages", "owner-A"]),
    ).toBeUndefined();
    expect(
      viewB.cache.getQueryData(["agent-room", "messages", "owner-A"]),
    ).toBeUndefined();
  });

  it("settling A's pending post after a full page reload cannot insert it into B", async () => {
    const pending = deferred<AgentRoomMessage>();
    rs.mocked(postAgentRoomMessage).mockImplementation(() => pending.promise);
    const viewA = mount();
    await waitFor(() => expect(viewA.result.current.room.data).toEqual([]));
    let outcome!: Promise<unknown>;
    act(() => {
      outcome = viewA.result.current.post
        .mutateAsync(INPUT)
        .catch((error: unknown) => error);
    });
    await waitFor(() => expect(postAgentRoomMessage).toHaveBeenCalledTimes(1));
    const viewB = reloadTo(viewA, OWNER_B);
    await waitFor(() => expect(viewB.result.current.room.data).toEqual([]));
    pending.resolve(message("owner-A"));
    const result = await outcome;
    expect(result).toBeInstanceOf(Error);
    await waitFor(() => expect(viewB.result.current.room.data).toEqual([]));
    expect(
      viewA.cache.getQueryData(["agent-room", "messages", "owner-A"]),
    ).toEqual([]);
    expect(
      viewB.cache.getQueryData(["agent-room", "messages", "owner-A"]),
    ).toBeUndefined();
    expect(
      viewB.cache.getQueryData(["agent-room", "messages", "owner-B"]),
    ).toEqual([]);
  });

  it("keeps a late post out of a fresh owner when neither page uses the preferences boundary", async () => {
    const pending = deferred<AgentRoomMessage>();
    rs.mocked(postAgentRoomMessage).mockImplementation(() => pending.promise);
    const viewA = mount(OWNER_A, false);
    await waitFor(() => expect(viewA.result.current.room.data).toEqual([]));
    let outcome!: Promise<unknown>;
    act(() => {
      outcome = viewA.result.current.post
        .mutateAsync(INPUT)
        .catch((error: unknown) => error);
    });
    await waitFor(() => expect(postAgentRoomMessage).toHaveBeenCalledTimes(1));
    const viewB = reloadTo(viewA, OWNER_B, false);
    await waitFor(() => expect(viewB.result.current.room.data).toEqual([]));
    pending.resolve(message("owner-A"));
    expect(await outcome).toBeInstanceOf(Error);
    await waitFor(() => expect(viewB.result.current.room.data).toEqual([]));
    expect(
      viewA.cache.getQueryData(["agent-room", "messages", "owner-A"]),
    ).toEqual([]);
    expect(
      viewB.cache.getQueryData(["agent-room", "messages", "owner-A"]),
    ).toBeUndefined();
  });

  it("rejects mixed-owner read responses without exposing their data", async () => {
    rs.mocked(listAgentRoomMessages).mockResolvedValue([
      message("owner-A"),
      message("owner-B"),
    ]);
    const view = mount();
    await waitFor(() => expect(view.result.current.room.isError).toBe(true));
    expect(view.result.current.room.data).toBeUndefined();
    expect(
      view.cache.getQueryData(["agent-room", "messages", "owner-A"]),
    ).toBeUndefined();
  });

  it("rejects a post receipt for another account before caching it", async () => {
    rs.mocked(postAgentRoomMessage).mockResolvedValue(message("owner-B"));
    const view = mount();
    await waitFor(() => expect(view.result.current.room.data).toEqual([]));
    await expect(view.result.current.post.mutateAsync(INPUT)).rejects.toThrow(
      /signed-in account/,
    );
    expect(
      view.cache.getQueryData(["agent-room", "messages", "owner-A"]),
    ).toEqual([]);
  });

  it("allows authorized reads while refusing a read-only owner's direct mutation", async () => {
    const view = mount({ ...OWNER_A, permissions: ["threads:read"] });
    await waitFor(() => expect(view.result.current.room.data).toEqual([]));
    await expect(view.result.current.post.mutateAsync(INPUT)).rejects.toThrow(
      /posting is unavailable/,
    );
    expect(postAgentRoomMessage).not.toHaveBeenCalled();
  });

  it("hides private cache while the real AuthProvider refresh is confirming identity", async () => {
    const reload = rs
      .spyOn(window.location, "reload")
      .mockImplementation(() => undefined);
    const pendingAuth = deferred<Response>();
    rs.spyOn(globalThis, "fetch").mockImplementation(() => pendingAuth.promise);
    rs.mocked(listAgentRoomMessages)
      .mockResolvedValueOnce([message("owner-A")])
      .mockResolvedValue([message("owner-B")]);
    const viewA = mount();
    await waitFor(() =>
      expect(viewA.result.current.room.data?.[0]?.user_id).toBe("owner-A"),
    );
    let refresh!: Promise<void>;
    act(() => {
      refresh = viewA.result.current.auth.refreshUser();
    });
    await waitFor(() => expect(viewA.result.current.auth.isLoading).toBe(true));
    expect(viewA.result.current.room.data).toBeUndefined();
    pendingAuth.resolve(
      new Response(JSON.stringify(OWNER_B), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    await act(async () => {
      await refresh;
    });
    expect(reload).toHaveBeenCalledTimes(1);
    viewA.unmount();
    const viewB = mount(OWNER_B);
    await waitFor(() =>
      expect(viewB.result.current.room.data?.[0]?.user_id).toBe("owner-B"),
    );
    expect(
      viewB.cache.getQueryData(["agent-room", "messages", "owner-A"]),
    ).toBeUndefined();
  });

  it("resolves and caches a pending post through a same-owner auth refresh mid-flight (f135)", async () => {
    const pendingPost = deferred<AgentRoomMessage>();
    rs.mocked(postAgentRoomMessage).mockImplementation(
      () => pendingPost.promise,
    );
    const pendingAuth = deferred<Response>();
    rs.spyOn(globalThis, "fetch").mockImplementation(() => pendingAuth.promise);
    const view = mount();
    await waitFor(() => expect(view.result.current.room.data).toEqual([]));

    let outcome!: Promise<AgentRoomMessage>;
    act(() => {
      outcome = view.result.current.post.mutateAsync(INPUT);
    });
    await waitFor(() => expect(postAgentRoomMessage).toHaveBeenCalledTimes(1));

    // A same-owner background refresh -- e.g. the visibility-change refetch
    // -- resolves to the *same* account while the post is still in flight.
    // This must never be mistaken for a real account switch.
    let refresh!: Promise<void>;
    act(() => {
      refresh = view.result.current.auth.refreshUser();
    });
    await waitFor(() => expect(view.result.current.auth.isLoading).toBe(true));

    // The server confirms the post while the local auth refresh is still
    // resolving (isLoading still true, so useAgentRoomAccess momentarily
    // reports ownerId === null even though no real account change is
    // happening).
    await act(async () => {
      pendingPost.resolve(message("owner-A"));
      await Promise.resolve();
    });

    await expect(outcome).resolves.toEqual(message("owner-A"));
    expect(postAgentRoomMessage).toHaveBeenCalledTimes(1);
    // Asserted before the auth refresh itself settles: once it does, the
    // messages query re-admits and its own (separately mocked) refetch
    // supersedes this optimistic entry, which is expected in production
    // (the server's own list would include the same message by then) but
    // would make this assertion about the fixture data, not the fix.
    expect(
      view.cache.getQueryData(["agent-room", "messages", "owner-A"]),
    ).toEqual([message("owner-A")]);

    pendingAuth.resolve(
      new Response(JSON.stringify(OWNER_A), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    await act(async () => {
      await refresh;
    });
    await waitFor(() => expect(view.result.current.auth.isLoading).toBe(false));
  });

  for (const user of [null, { ...OWNER_A, system_role: "user" as const }]) {
    it(`does not discover or read a private room for ${user ? "a nonadmin" : "a signed-out caller"}`, async () => {
      const view = mount(user);
      await act(async () => {
        await Promise.resolve();
      });
      expect(view.result.current.room.data).toBeUndefined();
      expect(fetchAgentRoomEnabled).not.toHaveBeenCalled();
      expect(listAgentRoomMessages).not.toHaveBeenCalled();
      await expect(view.result.current.post.mutateAsync(INPUT)).rejects.toThrow(
        /posting is unavailable/,
      );
    });
  }

  it("requires a fresh owner-specific admission after each full page identity reload", async () => {
    const firstGateA = deferred<boolean>();
    const gateB = deferred<boolean>();
    const secondGateA = deferred<boolean>();
    let ownerACalls = 0;
    rs.mocked(fetchAgentRoomEnabled).mockImplementation((ownerId: string) => {
      if (ownerId === "owner-B") return gateB.promise;
      ownerACalls += 1;
      return ownerACalls === 1 ? firstGateA.promise : secondGateA.promise;
    });
    // Each confirmed account change reloads the page, so the next owner's
    // admission starts with a fresh provider, query client and gate request.
    let view = mount(OWNER_A, false);
    firstGateA.resolve(true);
    await waitFor(() => expect(view.result.current.access.enabled).toBe(true));

    view = reloadTo(view, OWNER_B, false);
    await waitFor(() => expect(fetchAgentRoomEnabled).toHaveBeenCalledTimes(2));
    expect(view.result.current.access.enabled).toBe(false);
    gateB.resolve(true);
    await waitFor(() => expect(view.result.current.access.enabled).toBe(true));

    view = reloadTo(view, OWNER_A, false);
    await waitFor(() => expect(fetchAgentRoomEnabled).toHaveBeenCalledTimes(3));
    expect(view.result.current.access.enabled).toBe(false);
    secondGateA.resolve(true);
    await waitFor(() => expect(view.result.current.access.enabled).toBe(true));
  });
});
