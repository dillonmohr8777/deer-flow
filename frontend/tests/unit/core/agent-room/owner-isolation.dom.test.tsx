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
      room: useAgentRoomMessages(),
      post: usePostAgentRoomMessage(),
    }),
    { wrapper: Wrapper },
  );
  return { ...view, cache };
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
  it("hides owner A cache while authenticated B's read is pending through the actual preferences boundary", async () => {
    rs.mocked(listAgentRoomMessages).mockResolvedValueOnce([
      message("owner-A"),
    ]);
    const pendingB = deferred<AgentRoomMessage[]>();
    rs.mocked(listAgentRoomMessages).mockImplementation(() => pendingB.promise);
    const view = mount();
    await waitFor(() =>
      expect(view.result.current.room.data?.[0]?.user_id).toBe("owner-A"),
    );
    act(() => view.result.current.auth.applyUser(OWNER_B));
    await waitFor(() =>
      expect(view.result.current.auth.user?.id).toBe("owner-B"),
    );
    expect(
      view.result.current.room.data?.some((item) => item.user_id === "owner-A"),
    ).not.toBe(true);
    pendingB.resolve([message("owner-B")]);
    await waitFor(() =>
      expect(view.result.current.room.data?.[0]?.user_id).toBe("owner-B"),
    );
    expect(
      view.cache.getQueryData(["agent-room", "messages", "owner-A"]),
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

  it("cancels and fences a late owner A read after switching to B", async () => {
    const pendingA = deferred<AgentRoomMessage[]>();
    rs.mocked(listAgentRoomMessages)
      .mockImplementationOnce(() => pendingA.promise)
      .mockResolvedValue([message("owner-B")]);
    const view = mount();
    await waitFor(() => expect(listAgentRoomMessages).toHaveBeenCalledTimes(1));
    const signal = rs.mocked(listAgentRoomMessages).mock.calls[0]?.[1];
    act(() => view.result.current.auth.applyUser(OWNER_B));
    await waitFor(() =>
      expect(view.result.current.room.data?.[0]?.user_id).toBe("owner-B"),
    );
    expect(signal?.aborted).toBe(true);
    pendingA.resolve([message("owner-A")]);
    await act(async () => {
      await pendingA.promise;
    });
    expect(view.result.current.room.data).toEqual([message("owner-B")]);
    expect(
      view.cache.getQueryData(["agent-room", "messages", "owner-A"]),
    ).toBeUndefined();
  });

  it("settling an old owner's pending post cannot insert private data into B or update A after unmount", async () => {
    const pending = deferred<AgentRoomMessage>();
    rs.mocked(postAgentRoomMessage).mockImplementation(() => pending.promise);
    const view = mount();
    await waitFor(() => expect(view.result.current.room.data).toEqual([]));
    let outcome!: Promise<unknown>;
    act(() => {
      outcome = view.result.current.post
        .mutateAsync(INPUT)
        .catch((error: unknown) => error);
    });
    await waitFor(() => expect(postAgentRoomMessage).toHaveBeenCalledTimes(1));
    act(() => view.result.current.auth.applyUser(OWNER_B));
    await waitFor(() =>
      expect(view.result.current.auth.user?.id).toBe("owner-B"),
    );
    pending.resolve(message("owner-A"));
    const result = await outcome;
    expect(result).toBeInstanceOf(Error);
    await waitFor(() => expect(view.result.current.room.data).toEqual([]));
    expect(
      view.cache.getQueryData(["agent-room", "messages", "owner-A"]),
    ).toEqual([]);
    expect(
      view.cache.getQueryData(["agent-room", "messages", "owner-B"]),
    ).toEqual([]);
  });

  it("fences a late post even when a caller does not mount the preferences boundary", async () => {
    const pending = deferred<AgentRoomMessage>();
    rs.mocked(postAgentRoomMessage).mockImplementation(() => pending.promise);
    const view = mount(OWNER_A, false);
    await waitFor(() => expect(view.result.current.room.data).toEqual([]));
    let outcome!: Promise<unknown>;
    act(() => {
      outcome = view.result.current.post
        .mutateAsync(INPUT)
        .catch((error: unknown) => error);
    });
    await waitFor(() => expect(postAgentRoomMessage).toHaveBeenCalledTimes(1));
    act(() => view.result.current.auth.applyUser(OWNER_B));
    await waitFor(() =>
      expect(view.result.current.auth.user?.id).toBe("owner-B"),
    );
    pending.resolve(message("owner-A"));
    expect(await outcome).toBeInstanceOf(Error);
    await waitFor(() => expect(view.result.current.room.data).toEqual([]));
    expect(
      view.cache.getQueryData(["agent-room", "messages", "owner-A"]),
    ).toEqual([]);
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
    const pendingAuth = deferred<Response>();
    rs.spyOn(globalThis, "fetch").mockImplementation(() => pendingAuth.promise);
    rs.mocked(listAgentRoomMessages)
      .mockResolvedValueOnce([message("owner-A")])
      .mockResolvedValue([message("owner-B")]);
    const view = mount();
    await waitFor(() =>
      expect(view.result.current.room.data?.[0]?.user_id).toBe("owner-A"),
    );
    let refresh!: Promise<void>;
    act(() => {
      refresh = view.result.current.auth.refreshUser();
    });
    await waitFor(() => expect(view.result.current.auth.isLoading).toBe(true));
    expect(view.result.current.room.data).toBeUndefined();
    pendingAuth.resolve(
      new Response(JSON.stringify(OWNER_B), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    await act(async () => {
      await refresh;
    });
    await waitFor(() =>
      expect(view.result.current.room.data?.[0]?.user_id).toBe("owner-B"),
    );
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
});
