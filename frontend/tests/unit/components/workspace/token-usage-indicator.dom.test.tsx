import type { Message } from "@langchain/langgraph-sdk";
import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";

import { TokenUsageIndicator } from "@/components/workspace/token-usage-indicator";
import { enUS } from "@/core/i18n/locales/en-US";
import { tokenUsagePreferencesFromPreset } from "@/core/messages/usage-model";

rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({ locale: "en-US", t: enUS }),
}));

// Render the menu inline: the e2e design harness drives the real Radix menu.
rs.mock("@/components/ui/dropdown-menu", () => {
  const Pass = ({ children }: { children?: ReactNode }) => <>{children}</>;
  return {
    DropdownMenu: Pass,
    DropdownMenuTrigger: Pass,
    DropdownMenuContent: ({ children }: { children?: ReactNode }) => (
      <div data-testid="menu">{children}</div>
    ),
    DropdownMenuLabel: ({ children }: { children?: ReactNode }) => (
      <div>{children}</div>
    ),
    DropdownMenuRadioGroup: Pass,
    DropdownMenuRadioItem: Pass,
    DropdownMenuSeparator: () => <hr />,
  };
});

const human = { type: "human", id: "h1", content: "Hi" } as Message;
const reply = { type: "ai", id: "a1", content: "Hello" } as Message;

function renderIndicator(
  props: Partial<Parameters<typeof TokenUsageIndicator>[0]> = {},
) {
  return render(
    <TokenUsageIndicator
      enabled
      threadId="thread-1"
      messages={[human, reply]}
      preferences={tokenUsagePreferencesFromPreset("summary")}
      onPreferencesChange={() => undefined}
      {...props}
    />,
  );
}

function pill() {
  return screen.getByRole("button");
}

afterEach(cleanup);

describe("TokenUsageIndicator", () => {
  it("names the unit on every header figure", () => {
    renderIndicator({
      backendUsage: {
        inputTokens: 41_380,
        outputTokens: 6_830,
        totalTokens: 48_210,
      },
      contextUsage: {
        tokenCount: 72_800,
        maxContextTokens: 200_000,
        percentage: 36.4,
      },
    });
    expect(pill().textContent).toBe("48.2K tokens36.4% context");
  });

  it("explains the percentage as a share of the context window", () => {
    renderIndicator({
      contextUsage: {
        tokenCount: 72_800,
        maxContextTokens: 200_000,
        percentage: 36.4,
      },
    });
    const meter = screen.getByRole("meter", { name: "Context window" });
    expect(meter.getAttribute("aria-valuenow")).toBe("36.4");
    expect(screen.getByText("72,800 of 200,000 tokens (36.4%)")).toBeDefined();
    expect(screen.getByText(enUS.contextUsage.explanation)).toBeDefined();
  });

  it("says Unavailable when a reply exists but reported no usage", () => {
    renderIndicator();
    expect(pill().textContent).toBe("Tokens unavailable");
    expect(screen.getByText(enUS.tokenUsage.unavailable)).toBeDefined();
    expect(screen.getByText(enUS.contextUsage.unavailable)).toBeDefined();
    expect(screen.queryByRole("meter")).toBeNull();
    expect(document.body.textContent).not.toContain("usage_metadata");
  });

  it("shows no figure before the first reply, and none mid-stream", () => {
    const { unmount } = renderIndicator({ messages: [human] });
    expect(pill().textContent).toBe("Tokens");
    unmount();
    renderIndicator({ pendingMessages: [reply] });
    expect(pill().textContent).toBe("Tokens");
  });

  it("keeps the context reading unavailable without a known window size", () => {
    renderIndicator({
      contextUsage: { tokenCount: 900, maxContextTokens: null, percentage: 0 },
    });
    expect(pill().textContent).not.toContain("%");
    expect(screen.getByText(enUS.contextUsage.unavailable)).toBeDefined();
  });
});
