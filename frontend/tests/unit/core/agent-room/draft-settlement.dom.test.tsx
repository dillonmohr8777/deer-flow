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
import { AuthProvider } from "@/core/auth/AuthProvider";
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

const OWNER = { ...AUTH_DISABLED_USER, id: "synthetic-owner" };
const SUBMITTED_DRAFT = "  Synthetic instruction A  ";
beforeEach(() => {
  rs.mocked(fetchAgentRoomEnabled).mockResolvedValue(true);
  rs.mocked(listAgentRoomMessages).mockResolvedValue([]);
});
afterEach(() => {
  cleanup();
  rs.resetAllMocks();
  rs.restoreAllMocks();
});

describe("acknowledged Room posts retain newer same-owner drafts", () => {
  for (const { name, replacement, expected } of [
    {
      name: "retains a new draft typed while a prior post is pending",
      replacement: "Synthetic instruction B",
      expected: "Synthetic instruction B",
    },
    {
      name: "retains exact whitespace edits made while a prior post is pending",
      replacement: "Synthetic instruction A",
      expected: "Synthetic instruction A",
    },
    {
      name: "clears an unchanged submitted draft even when its wire body is trimmed",
      replacement: null,
      expected: "",
    },
  ]) {
    it(name, async () => {
      let settlePost!: (message: AgentRoomMessage) => void;
      rs.mocked(postAgentRoomMessage).mockImplementation(
        () =>
          new Promise((resolve) => {
            settlePost = resolve;
          }),
      );
      const cache = new QueryClient({
        defaultOptions: { queries: { retry: false } },
      });
      render(
        <AuthProvider initialUser={OWNER}>
          <QueryClientProvider client={cache}>
            <UserPreferencesBoundary>
              <AgentRoom />
            </UserPreferencesBoundary>
          </QueryClientProvider>
        </AuthProvider>,
      );
      const input = await screen.findByLabelText<HTMLTextAreaElement>(
        "Leave an instruction or note",
      );
      fireEvent.change(input, { target: { value: SUBMITTED_DRAFT } });
      fireEvent.click(screen.getByRole("button", { name: "Post to room" }));
      await waitFor(() =>
        expect(postAgentRoomMessage).toHaveBeenCalledTimes(1),
      );
      expect(postAgentRoomMessage).toHaveBeenCalledWith(
        { body: SUBMITTED_DRAFT.trim(), message_type: "instruction" },
        OWNER.id,
      );
      expect(input.disabled).toBe(false);
      expect(
        screen.getByRole<HTMLButtonElement>("button", { name: "Posting…" })
          .disabled,
      ).toBe(true);
      if (replacement !== null)
        fireEvent.change(input, { target: { value: replacement } });
      const receipt: AgentRoomMessage = {
        id: "acknowledged-A",
        user_id: OWNER.id,
        author_kind: "owner",
        agent_id: null,
        agent_role: "",
        message_type: "instruction",
        body: SUBMITTED_DRAFT.trim(),
        run_id: null,
        created_at: "2026-09-30T00:00:00Z",
      };
      await act(async () => {
        settlePost(receipt);
      });
      await waitFor(() =>
        expect(cache.getMutationCache().getAll()[0]?.state.status).toBe(
          "success",
        ),
      );
      expect(
        screen.getByLabelText<HTMLTextAreaElement>(
          "Leave an instruction or note",
        ).value,
      ).toBe(expected);
      expect(cache.getQueryData(["agent-room", "messages", OWNER.id])).toEqual([
        receipt,
      ]);
      expect(postAgentRoomMessage).toHaveBeenCalledTimes(1);
    });
  }
});
