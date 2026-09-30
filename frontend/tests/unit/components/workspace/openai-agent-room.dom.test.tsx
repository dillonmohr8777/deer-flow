import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { type PropsWithChildren } from "react";

const mocks = rs.hoisted(() => ({
  status: rs.fn(),
  list: rs.fn(),
  read: rs.fn(),
  send: rs.fn(),
  cancel: rs.fn(),
  download: rs.fn(),
  handOff: rs.fn(),
}));
rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: () => ({
    user: { id: "owner-one", permissions: ["runs:create", "runs:cancel"] },
  }),
}));
rs.mock("@/components/ui/sidebar", () => ({
  SidebarTrigger: () => <button aria-label="Toggle sidebar" />,
}));
rs.mock("@/core/openai-agents/api", () => ({
  getOpenAIAgentStatus: mocks.status,
  listAgentSessions: mocks.list,
  getAgentSession: mocks.read,
  submitAgentInput: mocks.send,
  cancelAgentTurn: mocks.cancel,
  downloadAgentArtifact: mocks.download,
  handOffAgentDownload: mocks.handOff,
  isAgentBusy: (status: string) =>
    [
      "creating",
      "in_progress",
      "running",
      "queued",
      "cancelling",
      "unknown",
      "requires_action",
    ].includes(status),
}));

import { OpenAIAgentRoom } from "@/components/workspace/openai-agent-room";
import { type AgentSession } from "@/core/openai-agents/api";

const STATUS = {
  owner_scope: "scope-one",
  configured: true,
  available: true,
  model: "gpt-6.1-sol",
  max_concurrent_subagents: 3,
  browser_available: false,
  reason: null,
};
const DETAIL: AgentSession = {
  id: "private-session",
  title: "Private task",
  status: "idle",
  created_at: "2026-09-29T23:00:00Z",
  updated_at: "2026-09-29T23:00:01Z",
  last_error: null,
  turn: { id: "root-turn", status: "completed", output_verified: true },
  items: [
    {
      id: "answer",
      type: "message",
      turn_id: "root-turn",
      subagent_id: null,
      role: "assistant",
      text: "Prior workspace private output",
      status: "completed",
      phase: "final_answer",
    },
  ],
  artifacts: [],
  required_actions: [],
  usage: null,
  operation_pending: false,
  history_truncated: false,
};
const clients: QueryClient[] = [];
function Wrapper({ children }: PropsWithChildren) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  clients.push(client);
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
beforeEach(() => {
  Object.values(mocks).forEach((mock) => mock.mockReset());
  mocks.status.mockResolvedValue(STATUS);
  mocks.list.mockResolvedValue({ data: [] });
  mocks.read.mockResolvedValue(DETAIL);
});
afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
});

describe("Agent room workspace fencing", () => {
  it("refreshes a changed cookie workspace after 409 and reads only its new scoped list", async () => {
    mocks.status
      .mockResolvedValueOnce(STATUS)
      .mockResolvedValue({ ...STATUS, owner_scope: "scope-two" });
    mocks.list
      .mockRejectedValueOnce(new Error("workspace_scope_changed"))
      .mockResolvedValue({ data: [] });
    render(<OpenAIAgentRoom />, { wrapper: Wrapper });
    await waitFor(() => expect(mocks.list).toHaveBeenCalledTimes(2));
    expect(mocks.list.mock.calls.map((call) => call[0])).toEqual([
      "scope-one",
      "scope-two",
    ]);
    expect(
      mocks.status.mock.calls.every((call) => call[0] === "owner-one"),
    ).toBe(true);
    expect(mocks.send).not.toHaveBeenCalled();
  });

  it("does not publish a late result from a previous workspace scope", async () => {
    let resolveAdmission: (data: AgentSession) => void = () => undefined;
    mocks.send.mockImplementation(
      () =>
        new Promise<AgentSession>((resolve) => {
          resolveAdmission = resolve;
        }),
    );
    render(<OpenAIAgentRoom />, { wrapper: Wrapper });
    await screen.findByText("Your sessions will appear here.");
    fireEvent.change(screen.getByLabelText("Task for the crew"), {
      target: { value: "Private task" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send task" }));
    await waitFor(() => expect(mocks.send).toHaveBeenCalledTimes(1));
    mocks.status.mockResolvedValue({ ...STATUS, owner_scope: "scope-two" });
    fireEvent.click(
      screen.getByRole("button", { name: "Refresh agent sessions" }),
    );
    await waitFor(() =>
      expect(
        mocks.list.mock.calls.some((call) => call[0] === "scope-two"),
      ).toBe(true),
    );
    resolveAdmission(DETAIL);
    await waitFor(() =>
      expect(
        screen
          .getByRole("button", { name: "New session" })
          .hasAttribute("disabled"),
      ).toBe(false),
    );
    expect(screen.queryByText("Prior workspace private output")).toBeNull();
    expect(mocks.read).not.toHaveBeenCalled();
  });
});
