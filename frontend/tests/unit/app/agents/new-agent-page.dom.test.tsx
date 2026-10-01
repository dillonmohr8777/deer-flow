import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import type { PropsWithChildren, ReactNode } from "react";

const mocks = rs.hoisted(() => ({
  onFinish: null as null | ((state: { messages: unknown[] }) => void),
  sendMessage: rs.fn(),
  getAgent: rs.fn(),
  checkAgentName: rs.fn(),
}));

rs.mock("next/navigation", () => ({
  useRouter: () => ({ push: rs.fn() }),
}));
rs.mock("sonner", () => ({ toast: { success: rs.fn(), error: rs.fn() } }));
rs.mock("@/components/ui/sidebar", () => ({
  SidebarTrigger: () => <button aria-label="Toggle sidebar" />,
}));
rs.mock("@/components/workspace/artifacts", () => ({
  ArtifactsProvider: ({ children }: PropsWithChildren) => <>{children}</>,
}));
rs.mock("@/components/workspace/messages", () => ({
  MessageList: () => <div />,
}));
rs.mock("@/components/ai-elements/prompt-input", () => ({
  PromptInput: ({ children }: { children: ReactNode }) => (
    <form>{children}</form>
  ),
  PromptInputFooter: ({ children }: PropsWithChildren) => <div>{children}</div>,
  PromptInputSubmit: () => <button type="submit">Send</button>,
  PromptInputTextarea: (props: { placeholder?: string }) => (
    <textarea aria-label="Message" placeholder={props.placeholder} />
  ),
}));
rs.mock("@/core/threads/hooks", () => ({
  hasToolResult: () => true,
  useThreadStream: (options: {
    onFinish: (state: { messages: unknown[] }) => void;
  }) => {
    mocks.onFinish = options.onFinish;
    return {
      thread: { isLoading: false, messages: [] },
      sendMessage: mocks.sendMessage,
    };
  },
}));
rs.mock("@/core/agents/api", () => {
  class AgentNameCheckError extends Error {}
  class AgentsApiDisabledError extends Error {}
  return {
    AgentNameCheckError,
    AgentsApiDisabledError,
    checkAgentName: mocks.checkAgentName,
    getAgent: mocks.getAgent,
  };
});

import NewAgentPage from "@/app/workspace/agents/new/page";
import { isBottomEdgeClaimed } from "@/components/workspace/workspace-tab-bar";
import { I18nProvider } from "@/core/i18n/context";

function Wrapper({ children }: PropsWithChildren) {
  return <I18nProvider initialLocale="en-US">{children}</I18nProvider>;
}

async function reachChatStep() {
  fireEvent.change(screen.getByLabelText("Name your new agent"), {
    target: { value: "seo-auditor" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Continue" }));
  await screen.findByRole("heading", { level: 1, name: "seo-auditor" });
}

async function saveAndFinish() {
  const save = screen.getByRole("button", { name: "Save agent" });
  save.focus();
  fireEvent.click(save);
  await waitFor(() => expect(mocks.sendMessage).toHaveBeenCalled());
  act(() => mocks.onFinish?.({ messages: [] }));
}

beforeEach(() => {
  mocks.onFinish = null;
  mocks.sendMessage.mockReset().mockResolvedValue(undefined);
  mocks.checkAgentName
    .mockReset()
    .mockResolvedValue({ available: true, name: "seo-auditor" });
  mocks.getAgent.mockReset();
});
afterEach(() => cleanup());

describe("New agent page", () => {
  it("claims the bottom edge in the chat step and releases it on unmount", async () => {
    const { unmount } = render(<NewAgentPage />, { wrapper: Wrapper });
    expect(isBottomEdgeClaimed()).toBe(false);
    await reachChatStep();
    expect(isBottomEdgeClaimed()).toBe(true);
    unmount();
    expect(isBottomEdgeClaimed()).toBe(false);
  });

  it("hands focus to the saved sheet when Save is replaced by the Saved tag", async () => {
    mocks.getAgent.mockResolvedValue({ name: "seo-auditor" });
    render(<NewAgentPage />, { wrapper: Wrapper });
    await reachChatStep();
    await saveAndFinish();
    const sheet = await screen.findByText(
      "seo-auditor is in your Agents, ready for its first job.",
    );
    expect(screen.getByText("Saved")).toBeDefined();
    await waitFor(() =>
      expect(document.activeElement).toBe(sheet.closest('[role="status"]')),
    );
  });

  it("says so on the page when the saved agent cannot be read back yet", async () => {
    mocks.getAgent.mockRejectedValue(new Error("not yet"));
    render(<NewAgentPage />, { wrapper: Wrapper });
    await reachChatStep();
    await saveAndFinish();
    await screen.findByText(
      /The agent was created, but MomoBot couldn't load it yet/,
      undefined,
      { timeout: 8000 },
    );
    expect(screen.queryByRole("button", { name: "Save agent" })).toBeNull();
  }, 15_000);
});
