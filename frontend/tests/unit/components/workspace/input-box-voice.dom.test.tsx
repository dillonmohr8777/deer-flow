import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

import { PromptInputProvider } from "@/components/ai-elements/prompt-input";
import { InputBox } from "@/components/workspace/input-box";
import { ThreadContext } from "@/components/workspace/messages/context";
import { AuthProvider } from "@/core/auth/AuthProvider";
import { DEFAULT_LOCALE } from "@/core/i18n";
import { I18nProvider } from "@/core/i18n/context";
import type {
  BrowserSpeechRecognition,
  SpeechRecognitionEventLike,
} from "@/core/voice-input/speech-recognition";

rs.mock("next/navigation", () => ({
  useRouter: () => ({ push: rs.fn(), replace: rs.fn(), refresh: rs.fn() }),
  usePathname: () => "/workspace/chats/new",
  useSearchParams: () => new URLSearchParams(),
}));

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

type SpeechWindow = {
  SpeechRecognition?: new () => BrowserSpeechRecognition;
  webkitSpeechRecognition?: new () => BrowserSpeechRecognition;
};

let lastRecognition: BrowserSpeechRecognition | null = null;

function recordRecognition(instance: BrowserSpeechRecognition) {
  lastRecognition = instance;
}

class FakeSpeechRecognition implements BrowserSpeechRecognition {
  continuous = false;
  interimResults = false;
  lang = "";
  maxAlternatives = 1;
  onend: (() => void) | null = null;
  onerror: ((event: { error?: string }) => void) | null = null;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null = null;

  constructor() {
    recordRecognition(this);
  }

  start = rs.fn();
  stop = rs.fn(() => {
    this.onend?.();
  });
  abort = rs.fn();
}

function renderComposer() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <I18nProvider initialLocale={DEFAULT_LOCALE}>
      <QueryClientProvider client={queryClient}>
        <AuthProvider
          initialUser={{
            id: "client-1",
            email: "fixture-owner",
            system_role: "client",
            needs_setup: false,
            oauth_provider: null,
          }}
        >
          <ThreadContext.Provider
            value={{ thread: { messages: [] } as never, isMock: true }}
          >
            <PromptInputProvider>
              <InputBox
                threadId="thread-voice-1"
                status="ready"
                context={{ mode: "flash" } as never}
              />
            </PromptInputProvider>
          </ThreadContext.Provider>
        </AuthProvider>
      </QueryClientProvider>
    </I18nProvider>,
  );
}

afterEach(() => {
  cleanup();
  lastRecognition = null;
  const win = window as unknown as SpeechWindow;
  delete win.SpeechRecognition;
  delete win.webkitSpeechRecognition;
});

describe("InputBox built-in voice dictation", () => {
  it("keeps the mic button disabled gracefully when Web Speech API is unsupported", () => {
    renderComposer();
    const button = screen.getByTestId("voice-input-button");
    expect(button.hasAttribute("disabled")).toBe(true);
    expect(button.textContent).toContain("Voice");
  });

  it("starts dictation, shows live Listening status, transcribes into the prompt input, and stops cleanly", async () => {
    const win = window as unknown as SpeechWindow;
    win.webkitSpeechRecognition = FakeSpeechRecognition;

    const { container } = renderComposer();
    const button = screen.getByTestId("voice-input-button");
    await waitFor(() => {
      expect(button.hasAttribute("disabled")).toBe(false);
    });

    fireEvent.click(button);

    expect(lastRecognition).not.toBeNull();
    expect(lastRecognition?.start).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("voice-input-status").textContent).toContain(
      "Listening...",
    );
    expect(button.getAttribute("aria-pressed")).toBe("true");
    expect(button.textContent).toContain("Stop");

    lastRecognition?.onresult?.({
      results: {
        length: 1,
        0: {
          isFinal: true,
          length: 1,
          0: { transcript: "Build my local plumbing homepage" },
        },
      },
    });

    const textarea = container.querySelector("textarea");
    await waitFor(() => {
      expect(textarea?.value).toBe("Build my local plumbing homepage");
    });

    fireEvent.click(button);
    expect(lastRecognition?.stop).toHaveBeenCalledTimes(1);
    await waitFor(() => {
      expect(screen.queryByTestId("voice-input-status")).toBeNull();
    });
  });
});
