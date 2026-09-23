import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";

import { PromptInputProvider } from "@/components/ai-elements/prompt-input";
import { InputBox } from "@/components/workspace/input-box";
import { ThreadContext } from "@/components/workspace/messages/context";
import { Welcome } from "@/components/workspace/welcome";
import { AuthProvider } from "@/core/auth/AuthProvider";
import { DEFAULT_LOCALE } from "@/core/i18n";
import { I18nProvider } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";

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

afterEach(cleanup);

function renderWelcomeComposer(onSubmit: () => void) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
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
                threadId="thread-1"
                status="ready"
                context={{ mode: "flash" } as never}
                onSubmit={onSubmit}
                isWelcomeMode
              />
            </PromptInputProvider>
          </ThreadContext.Provider>
        </AuthProvider>
      </QueryClientProvider>
    </I18nProvider>,
  );
}

describe("empty thread", () => {
  it("shows the lead Momo as decoration beside one line", () => {
    const { container } = render(
      <I18nProvider initialLocale={DEFAULT_LOCALE}>
        <Welcome />
      </I18nProvider>,
    );
    const momo = container.querySelector("img");
    expect(momo?.getAttribute("src")).toBe("/momentum/momos/lead.svg");
    expect(momo?.getAttribute("alt")).toBe("");
    expect(momo?.getAttribute("aria-hidden")).toBe("true");
    expect(
      screen.getByRole("heading", { name: enUS.welcome.greeting }),
    ).toBeDefined();
    expect(container.querySelectorAll("p")).toHaveLength(0);
  });

  it("offers three starters that fill the composer without sending", async () => {
    const onSubmit = rs.fn();
    const { container } = renderWelcomeComposer(onSubmit);

    const group = screen.getByRole("group", {
      name: enUS.inputBox.startersLabel,
    });
    const starters = within(group).getAllByRole("button");
    expect(starters.map((button) => button.textContent)).toEqual(
      enUS.inputBox.starters.map((starter) => starter.label),
    );
    expect(container.textContent).not.toContain("Surprise");

    fireEvent.click(starters[0]!);

    const textarea = container.querySelector("textarea")!;
    const prompt = enUS.inputBox.starters[0]!.prompt;
    await waitFor(() => expect(textarea.value).toBe(prompt));
    await waitFor(() => expect(document.activeElement).toBe(textarea));
    expect(
      textarea.value.slice(textarea.selectionStart, textarea.selectionEnd),
    ).toBe("[client]");
    expect(onSubmit).not.toHaveBeenCalled();
  });
});
