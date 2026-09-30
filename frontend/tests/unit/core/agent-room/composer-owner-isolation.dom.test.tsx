import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import type { ReactNode } from "react";

import { AgentRoom } from "@/components/workspace/agent-room/agent-room";
import {
  fetchAgentRoomEnabled,
  listAgentRoomMessages,
  postAgentRoomMessage,
} from "@/core/agent-room/api";
import type { AgentRoomMessage } from "@/core/agent-room/types";
import { AUTH_DISABLED_USER } from "@/core/auth/auth-disabled-user";
import { AuthProvider, useAuth } from "@/core/auth/AuthProvider";
import { UserPreferencesBoundary } from "@/core/settings/user-preferences-boundary";

const { replace } = rs.hoisted(() => ({ replace: rs.fn() }));
rs.mock("next/navigation", () => ({
  useRouter: () => ({ push: rs.fn(), replace }),
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
// Keep the real composer, auth and preferences lifecycle; remove only layout
// and unrelated header widgets that have their own browser coverage.
rs.mock("@/components/ui/scroll-area", () => ({
  ScrollArea: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}));
rs.mock("@/components/workspace/workspace-container", () => ({
  WorkspaceContainer: ({ children }: { children: ReactNode }) => (
    <div>{children}</div>
  ),
  WorkspaceBody: ({ children }: { children: ReactNode }) => (
    <div>{children}</div>
  ),
  WorkspaceHeader: () => null,
}));
rs.mock("@/components/workspace/page-body", () => ({
  pageStyles: {},
  WorkingState: () => null,
  EmptyState: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  ErrorState: () => null,
  StatusTag: ({ children }: { children: ReactNode }) => <span>{children}</span>,
}));

const OWNER_A = { ...AUTH_DISABLED_USER, id: "owner-A" };
const OWNER_B = { ...AUTH_DISABLED_USER, id: "owner-B" };

function AccountSwitch() {
  const { applyUser } = useAuth();
  return <button onClick={() => applyUser(OWNER_B)}>Switch account</button>;
}

beforeEach(() => {
  rs.mocked(fetchAgentRoomEnabled).mockResolvedValue(true);
  rs.mocked(listAgentRoomMessages).mockResolvedValue([]);
  replace.mockClear();
});
afterEach(() => {
  cleanup();
  rs.resetAllMocks();
});

describe("actual Room composer account lifecycle", () => {
  it("retains B's new draft when A's pending owner post settles after a real boundary switch", async () => {
    let settle!: (message: AgentRoomMessage) => void;
    rs.mocked(postAgentRoomMessage).mockImplementation(
      () =>
        new Promise((resolve) => {
          settle = resolve;
        }),
    );
    const cache = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <AuthProvider initialUser={OWNER_A}>
        <QueryClientProvider client={cache}>
          <AccountSwitch />
          <UserPreferencesBoundary>
            <AgentRoom />
          </UserPreferencesBoundary>
        </QueryClientProvider>
      </AuthProvider>,
    );
    const input = await screen.findByLabelText("Leave an instruction or note");
    fireEvent.change(input, { target: { value: "Owner A private draft" } });
    fireEvent.click(screen.getByRole("button", { name: "Post to room" }));
    await waitFor(() => expect(postAgentRoomMessage).toHaveBeenCalledTimes(1));
    const oldMutation = cache.getMutationCache().getAll()[0]!;
    fireEvent.click(screen.getByRole("button", { name: "Switch account" }));
    const newInput = await screen.findByLabelText(
      "Leave an instruction or note",
    );
    expect((newInput as HTMLTextAreaElement).value).toBe("");
    fireEvent.change(newInput, { target: { value: "Owner B retained draft" } });
    await act(async () => {
      settle({
        id: "late-A",
        user_id: "owner-A",
        author_kind: "owner",
        agent_id: null,
        agent_role: "",
        message_type: "instruction",
        body: "Owner A private draft",
        run_id: null,
        created_at: "2026-09-29T14:00:00Z",
      });
    });
    await waitFor(() => expect(oldMutation.state.status).toBe("error"));
    expect(
      screen.getByLabelText<HTMLTextAreaElement>("Leave an instruction or note")
        .value,
    ).toBe("Owner B retained draft");
    expect(screen.queryByText("Owner A private draft")).toBeNull();
    expect(cache.getQueryData(["agent-room", "messages", "owner-B"])).toEqual(
      [],
    );
  });

  it("shows the authorized feed but disables posting for a read-only owner", async () => {
    const cache = new QueryClient();
    render(
      <AuthProvider initialUser={{ ...OWNER_A, permissions: ["threads:read"] }}>
        <QueryClientProvider client={cache}>
          <UserPreferencesBoundary>
            <AgentRoom />
          </UserPreferencesBoundary>
        </QueryClientProvider>
      </AuthProvider>,
    );
    const input = await screen.findByLabelText("Leave an instruction or note");
    expect((input as HTMLTextAreaElement).disabled).toBe(true);
    expect(
      screen.getByRole<HTMLButtonElement>("button", { name: "Post to room" })
        .disabled,
    ).toBe(true);
    expect(postAgentRoomMessage).not.toHaveBeenCalled();
  });

  it("does not refetch access on a window focus event (f134)", async () => {
    const cache = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <AuthProvider initialUser={OWNER_A}>
        <QueryClientProvider client={cache}>
          <UserPreferencesBoundary>
            <AgentRoom />
          </UserPreferencesBoundary>
        </QueryClientProvider>
      </AuthProvider>,
    );
    await screen.findByLabelText("Leave an instruction or note");
    expect(fetchAgentRoomEnabled).toHaveBeenCalledTimes(1);
    // React Query's focusManager listens for `visibilitychange` on `window`,
    // not `focus` (verified against @tanstack/query-core's own source) --
    // this is the event `refetchOnWindowFocus: false` actually suppresses.
    await act(async () => {
      window.dispatchEvent(new Event("visibilitychange"));
      await Promise.resolve();
    });
    expect(fetchAgentRoomEnabled).toHaveBeenCalledTimes(1);
  });

  it("keeps the composer and draft through a same-owner tab-refocus refresh, and never redirects (f134 review)", async () => {
    rs.mocked(fetchAgentRoomEnabled)
      .mockResolvedValueOnce(true) // initial admission
      .mockRejectedValueOnce(new Error("network blip")); // the fresh discovery fired once the refresh resolves back to the same owner
    const authMe = rs.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(OWNER_A), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const cache = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <AuthProvider initialUser={OWNER_A}>
        <QueryClientProvider client={cache}>
          <UserPreferencesBoundary>
            <AgentRoom />
          </UserPreferencesBoundary>
        </QueryClientProvider>
      </AuthProvider>,
    );
    const input = await screen.findByLabelText("Leave an instruction or note");
    fireEvent.change(input, {
      target: { value: "Draft survives a same-owner tab refocus" },
    });

    // AuthProvider listens for `visibilitychange` on `document` and calls
    // `refreshUser()` for the signed-in owner -- the real trigger behind
    // this finding's reproduction, distinct from React Query's own
    // window-level focus listener exercised above.
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await waitFor(() => expect(authMe).toHaveBeenCalled());
    await waitFor(() => expect(fetchAgentRoomEnabled).toHaveBeenCalledTimes(2));
    await waitFor(() =>
      expect(
        cache.getQueryState(["agent-room", "access", "owner-A"])?.fetchStatus,
      ).toBe("idle"),
    );

    expect(
      screen.getByLabelText<HTMLTextAreaElement>("Leave an instruction or note")
        .value,
    ).toBe("Draft survives a same-owner tab refocus");
    expect(replace).not.toHaveBeenCalled();
  });

  it("hides the room when a tab-refocus refresh returns a different owner (f134 review)", async () => {
    rs.mocked(fetchAgentRoomEnabled).mockResolvedValue(true);
    rs.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(OWNER_B), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const cache = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <AuthProvider initialUser={OWNER_A}>
        <QueryClientProvider client={cache}>
          <UserPreferencesBoundary>
            <AgentRoom />
          </UserPreferencesBoundary>
        </QueryClientProvider>
      </AuthProvider>,
    );
    await screen.findByLabelText("Leave an instruction or note");

    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
    });

    // B is a real, different owner: re-earning admission is correct, not a
    // bug -- unlike the same-owner case above, this one may legitimately
    // show the loading view while B's own fresh discovery runs.
    await waitFor(() =>
      expect(
        screen.queryByLabelText("Leave an instruction or note"),
      ).toBeNull(),
    );
  });

  it("hides the room when a tab-refocus refresh comes back 401 (f134 review)", async () => {
    rs.mocked(fetchAgentRoomEnabled).mockResolvedValue(true);
    rs.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(null, { status: 401 }),
    );
    const cache = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <AuthProvider initialUser={OWNER_A}>
        <QueryClientProvider client={cache}>
          <UserPreferencesBoundary>
            <AgentRoom />
          </UserPreferencesBoundary>
        </QueryClientProvider>
      </AuthProvider>,
    );
    await screen.findByLabelText("Leave an instruction or note");

    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
    });

    await waitFor(() =>
      expect(
        screen.queryByLabelText("Leave an instruction or note"),
      ).toBeNull(),
    );
  });

  it("keeps the composer and draft through a background access refetch that merely fails, and does not redirect (f134)", async () => {
    rs.mocked(fetchAgentRoomEnabled)
      .mockResolvedValueOnce(true)
      .mockRejectedValueOnce(new Error("network blip"));
    const cache = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <AuthProvider initialUser={OWNER_A}>
        <QueryClientProvider client={cache}>
          <UserPreferencesBoundary>
            <AgentRoom />
          </UserPreferencesBoundary>
        </QueryClientProvider>
      </AuthProvider>,
    );
    const input = await screen.findByLabelText("Leave an instruction or note");
    fireEvent.change(input, {
      target: { value: "Draft survives a rejected refocus refetch" },
    });

    await act(async () => {
      await cache
        .refetchQueries({ queryKey: ["agent-room", "access", "owner-A"] })
        .catch(() => {
          // The rejection is the point of this test; only the UI's reaction matters.
        });
    });
    // The query settling and React committing the resulting re-render are
    // two separate ticks; wait for the query itself to go idle before
    // asserting on the DOM it drives.
    await waitFor(() =>
      expect(
        cache.getQueryState(["agent-room", "access", "owner-A"])?.fetchStatus,
      ).toBe("idle"),
    );

    expect(fetchAgentRoomEnabled).toHaveBeenCalledTimes(2);
    expect(
      screen.getByLabelText<HTMLTextAreaElement>("Leave an instruction or note")
        .value,
    ).toBe("Draft survives a rejected refocus refetch");
    expect(replace).not.toHaveBeenCalled();
  });

  it("still redirects when a later access refetch resolves false, even after prior admission (f134)", async () => {
    rs.mocked(fetchAgentRoomEnabled)
      .mockResolvedValueOnce(true)
      .mockResolvedValueOnce(false);
    const cache = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <AuthProvider initialUser={OWNER_A}>
        <QueryClientProvider client={cache}>
          <UserPreferencesBoundary>
            <AgentRoom />
          </UserPreferencesBoundary>
        </QueryClientProvider>
      </AuthProvider>,
    );
    await screen.findByLabelText("Leave an instruction or note");

    await act(async () => {
      await cache.refetchQueries({
        queryKey: ["agent-room", "access", "owner-A"],
      });
    });

    await waitFor(() =>
      expect(replace).toHaveBeenCalledWith("/workspace/command-center"),
    );
  });
});
