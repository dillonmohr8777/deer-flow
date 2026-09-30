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
});
