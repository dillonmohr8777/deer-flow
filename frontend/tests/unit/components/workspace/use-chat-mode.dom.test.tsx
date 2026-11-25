import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { act, cleanup, render } from "@testing-library/react";

import { useSpecificChatMode } from "@/components/workspace/chats/use-chat-mode";

const mockNav = rs.hoisted(() => ({
  threadId: "new",
  promptParam: "" as string | null,
}));

const mockComposer = rs.hoisted(() => ({
  value: "",
  setInput: rs.fn((next: string) => {
    mockComposer.value = next;
  }),
}));

const mockToast = rs.hoisted(() =>
  rs.fn(
    (
      _message: string,
      _opts?: {
        description?: string;
        action?: { label: string; onClick: () => void };
        cancel?: { label: string; onClick: () => void };
      },
    ) => undefined,
  ),
);

rs.mock("next/navigation", () => ({
  useParams: () => ({ thread_id: mockNav.threadId }),
  useSearchParams: () => {
    const params = new URLSearchParams();
    if (mockNav.promptParam) {
      params.set("prompt", mockNav.promptParam);
    }
    return params;
  },
}));

rs.mock("@/components/ai-elements/prompt-input", () => ({
  usePromptInputController: () => ({
    textInput: {
      value: mockComposer.value,
      setInput: mockComposer.setInput,
    },
  }),
}));

rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    t: { inputBox: { createSkillPrompt: "Create a skill" } },
  }),
}));

rs.mock("sonner", () => ({
  toast: mockToast,
}));

function Harness() {
  useSpecificChatMode();
  return <textarea value={mockComposer.value} readOnly />;
}

beforeEach(() => {
  rs.useFakeTimers();
  mockNav.threadId = "new";
  mockNav.promptParam = null;
  mockComposer.value = "";
  mockComposer.setInput.mockClear();
  mockToast.mockClear();
});

afterEach(() => {
  cleanup();
  rs.useRealTimers();
});

describe("useSpecificChatMode", () => {
  it("applies URL prompt immediately when the composer is empty", () => {
    mockNav.promptParam = "Build my website";
    render(<Harness />);

    act(() => {
      rs.advanceTimersByTime(120);
    });

    expect(mockComposer.setInput).toHaveBeenCalledWith("Build my website");
    expect(mockToast).not.toHaveBeenCalled();
  });

  it("offers a non-destructive replacement when a draft exists and applies once the draft is cleared or accepted", () => {
    mockComposer.value = "Unsent draft notes";
    mockNav.promptParam = "Draft weekly GBP pack";
    const { rerender } = render(<Harness />);

    act(() => {
      rs.advanceTimersByTime(120);
    });

    // Existing draft is preserved and user is offered replacement.
    expect(mockComposer.setInput).not.toHaveBeenCalled();
    expect(mockToast).toHaveBeenCalledTimes(1);

    // Clearing the draft lets the unhandled workflow prompt apply automatically.
    mockComposer.value = "";
    rerender(<Harness />);
    act(() => {
      rs.advanceTimersByTime(120);
    });
    expect(mockComposer.setInput).toHaveBeenCalledWith("Draft weekly GBP pack");
  });

  it("replaces the draft when the user clicks Use workflow prompt and respects Keep draft", () => {
    mockComposer.value = "Existing user text";
    mockNav.promptParam = "Create Google Ads strategy";
    const { rerender } = render(<Harness />);

    act(() => {
      rs.advanceTimersByTime(120);
    });

    expect(mockToast).toHaveBeenCalledTimes(1);
    const firstOpts = mockToast.mock.calls[0]?.[1];
    expect(firstOpts?.action?.label).toBe("Use workflow prompt");
    firstOpts?.action?.onClick();
    expect(mockComposer.setInput).toHaveBeenCalledWith(
      "Create Google Ads strategy",
    );

    // Navigating to a new workflow prompt while text exists offers again; Keep draft declines it.
    mockComposer.setInput.mockClear();
    mockToast.mockClear();
    mockComposer.value = "Edited ads prompt";
    mockNav.promptParam = "Write local SEO blog";
    rerender(<Harness />);
    act(() => {
      rs.advanceTimersByTime(120);
    });
    expect(mockToast).toHaveBeenCalledTimes(1);
    mockToast.mock.calls[0]?.[1]?.cancel?.onClick();

    // After declining, clearing the draft does NOT re-inject the declined prompt.
    mockComposer.value = "";
    rerender(<Harness />);
    act(() => {
      rs.advanceTimersByTime(120);
    });
    expect(mockComposer.setInput).not.toHaveBeenCalled();
  });
});
