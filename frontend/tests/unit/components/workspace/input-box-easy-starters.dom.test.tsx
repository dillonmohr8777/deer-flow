import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import type { ReactNode } from "react";

import { PromptInputProvider } from "@/components/ai-elements/prompt-input";
import { InputBox } from "@/components/workspace/input-box";
import { ThreadContext } from "@/components/workspace/messages/context";
import { AuthProvider } from "@/core/auth/AuthProvider";
import { DEFAULT_LOCALE } from "@/core/i18n";
import { I18nProvider } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";

rs.mock("next/navigation", () => ({
  useRouter: () => ({ push: rs.fn(), replace: rs.fn(), refresh: rs.fn() }),
  usePathname: () => "/workspace",
  useSearchParams: () => new URLSearchParams(),
}));

// Easy starters never call the AI follow-up endpoint; keep the composer's
// model selector out of the way like the sibling gating suites do.
rs.mock("@/core/models/hooks", () => ({
  useModels: () => ({
    models: [],
    tokenUsageEnabled: false,
    isLoading: false,
    isFetching: false,
    error: null,
    refetch: rs.fn(),
  }),
}));

function typeText(container: HTMLElement, value: string): void {
  const textarea = container.querySelector("textarea");
  if (!(textarea instanceof HTMLTextAreaElement)) {
    throw new Error("composer textarea not rendered");
  }
  fireEvent.change(textarea, { target: { value } });
}

function submitForm(container: HTMLElement, text: string) {
  typeText(container, text);
  const form = container.querySelector("form");
  if (!(form instanceof HTMLFormElement)) {
    throw new Error("composer form not rendered");
  }
  fireEvent.submit(form);
}

function getSubmitButton(container: HTMLElement): HTMLButtonElement {
  const button = container.querySelector('button[type="submit"]');
  if (!(button instanceof HTMLButtonElement)) {
    throw new Error("submit button not rendered");
  }
  return button;
}

function queryStarters(): HTMLElement | null {
  return screen.queryByText(enUS.inputBox.easyStarterHelp);
}

function mockCommandRequests() {
  const fetchMock = rs.fn(async () => {
    return new Response(JSON.stringify({ goal: null, compacted: true }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  });
  rs.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function Composer({
  status,
  onStop,
  onSubmit,
  threadId = "thread-1",
}: {
  status: "ready" | "streaming";
  onStop?: () => void;
  onSubmit: () => void | Promise<void>;
  threadId?: string;
}): ReactNode {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return (
    <I18nProvider initialLocale={DEFAULT_LOCALE}>
      <QueryClientProvider client={queryClient}>
        <AuthProvider
          initialUser={{
            id: "user-1",
            email: "user@example.test",
            system_role: "user",
            needs_setup: false,
            oauth_provider: null,
          }}
        >
          <ThreadContext.Provider
            value={{ thread: { messages: [] } as never, isMock: true }}
          >
            <PromptInputProvider>
              <InputBox
                threadId={threadId}
                status={status}
                context={{ mode: "flash", experience_mode: "easy" } as never}
                onStop={onStop}
                onSubmit={onSubmit}
                canStopStreaming
                canCreateRuns
              />
            </PromptInputProvider>
          </ThreadContext.Provider>
        </AuthProvider>
      </QueryClientProvider>
    </I18nProvider>
  );
}

beforeEach(() => {
  window.sessionStorage.clear();
});

afterEach(() => {
  rs.restoreAllMocks();
  rs.unstubAllGlobals();
  cleanup();
});

describe("InputBox Easy mode starters", () => {
  it("hides starters on Stop but shows them again once the next turn finishes", async () => {
    mockCommandRequests();
    const onStop = rs.fn();
    const onSubmit = rs.fn(() => Promise.resolve());
    const { container, rerender } = render(
      <Composer status="ready" onStop={onStop} onSubmit={onSubmit} />,
    );

    expect(queryStarters()).not.toBeNull();

    // Start a turn and stop it mid-stream.
    rerender(
      <Composer status="streaming" onStop={onStop} onSubmit={onSubmit} />,
    );
    fireEvent.click(getSubmitButton(container));
    expect(onStop).toHaveBeenCalledTimes(1);

    // Interrupted turn: starters correctly stay hidden for it.
    rerender(<Composer status="ready" onStop={onStop} onSubmit={onSubmit} />);
    expect(queryStarters()).toBeNull();

    // The user was never asked and never dismissed anything; the very next
    // message they send should bring the starters back once it completes.
    submitForm(container, "let's try again");
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    rerender(
      <Composer status="streaming" onStop={onStop} onSubmit={onSubmit} />,
    );
    rerender(<Composer status="ready" onStop={onStop} onSubmit={onSubmit} />);

    expect(queryStarters()).not.toBeNull();
  });

  it("keeps starters hidden after an explicit close, through submit and /goal", async () => {
    mockCommandRequests();
    const onSubmit = rs.fn(() => Promise.resolve());
    const { container, rerender } = render(
      <Composer status="ready" onSubmit={onSubmit} />,
    );

    expect(queryStarters()).not.toBeNull();

    const closeButton = screen.getByRole("button", {
      name: enUS.common.close,
    });
    fireEvent.click(closeButton);
    expect(queryStarters()).toBeNull();

    // A real dismissal survives a normal message round trip...
    submitForm(container, "still no starters please");
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    rerender(<Composer status="streaming" onSubmit={onSubmit} />);
    rerender(<Composer status="ready" onSubmit={onSubmit} />);
    expect(queryStarters()).toBeNull();

    // ...and a /goal command too.
    submitForm(container, "/goal ship the fix");
    await waitFor(() =>
      expect(container.querySelector("textarea")?.value).toBe(""),
    );
    expect(queryStarters()).toBeNull();
  });

  it("scopes a dismissal to its own thread: a different thread shows starters again", () => {
    const onSubmit = rs.fn(() => Promise.resolve());
    const { rerender } = render(
      <Composer status="ready" onSubmit={onSubmit} threadId="thread-1" />,
    );

    fireEvent.click(screen.getByRole("button", { name: enUS.common.close }));
    expect(queryStarters()).toBeNull();

    // Switching to a different, unrelated conversation is not "the next
    // turn" of the dismissed one -- it should not inherit the dismissal.
    rerender(
      <Composer status="ready" onSubmit={onSubmit} threadId="thread-2" />,
    );
    expect(queryStarters()).not.toBeNull();
  });

  it("tapping a starter with a draft present asks for confirmation instead of sending", () => {
    const onSubmit = rs.fn(() => Promise.resolve());
    const { container } = render(
      <Composer status="ready" onSubmit={onSubmit} />,
    );

    typeText(container, "my own draft");
    fireEvent.click(screen.getByText(enUS.inputBox.easyStarterHelp));

    expect(onSubmit).not.toHaveBeenCalled();
    expect(queryStarters()).not.toBeNull();
    expect(container.querySelector("textarea")?.value).toBe("my own draft");
  });
});
