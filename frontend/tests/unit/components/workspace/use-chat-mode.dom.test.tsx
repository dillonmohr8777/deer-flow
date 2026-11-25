import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { act, cleanup, render } from "@testing-library/react";

import { useSpecificChatMode } from "@/components/workspace/chats/use-chat-mode";

const mockNav = rs.hoisted(() => ({
  pathname: "/workspace/chats/new",
  threadId: "new",
  promptParam: "" as string | null,
}));

const mockComposer = rs.hoisted(() => ({
  value: "",
  setInput: rs.fn((next: string) => {
    mockComposer.value = next;
  }),
}));

const mockToastDismiss = rs.hoisted(() => rs.fn((_id?: string | number) => undefined));
const mockToast = rs.hoisted(() => {
  let seq = 1;
  const fn = rs.fn(
    (
      _message: string,
      _opts?: {
        description?: string;
        action?: { label: string; onClick: () => void };
        cancel?: { label: string; onClick: () => void };
      },
    ) => `toast-${seq++}`,
  );
  return Object.assign(fn, { dismiss: mockToastDismiss });
});

rs.mock("next/navigation", () => ({
  usePathname: () => mockNav.pathname,
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
  mockNav.pathname = "/workspace/chats/new";
  mockNav.threadId = "new";
  mockNav.promptParam = null;
  mockComposer.value = "";
  mockComposer.setInput.mockClear();
  mockToast.mockClear();
  mockToastDismiss.mockClear();
});

afterEach(() => {
  cleanup();
  rs.useRealTimers();
});

describe("useSpecificChatMode", () => {
  it("applies URL prompt immediately when the composer is empty and re-applies after leaving and revisiting", () => {
    mockNav.promptParam = "Build my website";
    const { rerender } = render(<Harness />);

    act(() => {
      rs.advanceTimersByTime(120);
    });
    expect(mockComposer.setInput).toHaveBeenCalledWith("Build my website");
    expect(mockToast).not.toHaveBeenCalled();

    // Navigate away to another thread with no prompt.
    mockComposer.setInput.mockClear();
    mockNav.pathname = "/workspace/chats/thread-42";
    mockNav.threadId = "thread-42";
    mockNav.promptParam = null;
    mockComposer.value = "";
    rerender(<Harness />);

    // Revisit the same workflow prompt on a fresh chat: it must apply again.
    mockNav.pathname = "/workspace/chats/new";
    mockNav.threadId = "new";
    mockNav.promptParam = "Build my website";
    mockComposer.value = "";
    rerender(<Harness />);
    act(() => {
      rs.advanceTimersByTime(120);
    });
    expect(mockComposer.setInput).toHaveBeenCalledWith("Build my website");
  });

  it("offers a non-destructive replacement when a draft exists and applies once the draft is cleared", () => {
    mockComposer.value = "Unsent draft notes";
    mockNav.promptParam = "Draft weekly GBP pack";
    const { rerender } = render(<Harness />);

    act(() => {
      rs.advanceTimersByTime(120);
    });

    expect(mockComposer.setInput).not.toHaveBeenCalled();
    expect(mockToast).toHaveBeenCalledTimes(1);

    mockComposer.value = "";
    rerender(<Harness />);
    act(() => {
      rs.advanceTimersByTime(120);
    });
    expect(mockComposer.setInput).toHaveBeenCalledWith("Draft weekly GBP pack");
  });

  it("dismisses and invalidates stale toast actions after switching chats", () => {
    mockComposer.value = "Existing draft on new chat";
    mockNav.promptParam = "Create Google Ads strategy";
    const { rerender } = render(<Harness />);

    act(() => {
      rs.advanceTimersByTime(120);
    });
    expect(mockToast).toHaveBeenCalledTimes(1);
    const staleToastAction = mockToast.mock.calls[0]?.[1]?.action?.onClick;
    expect(staleToastAction).toBeTruthy();

    // Switch to an unrelated chat with its own unsent draft.
    mockNav.pathname = "/workspace/chats/thread-99";
    mockNav.threadId = "thread-99";
    mockNav.promptParam = null;
    mockComposer.value = "Unrelated thread draft";
    rerender(<Harness />);

    expect(mockToastDismiss).toHaveBeenCalledTimes(1);

    // Clicking the old toast action after navigation must NOT touch the new chat composer.
    staleToastAction?.();
    expect(mockComposer.setInput).not.toHaveBeenCalled();
    expect(mockComposer.value).toBe("Unrelated thread draft");
  });

  it("replaces draft on Use workflow prompt and respects Keep draft", () => {
    mockComposer.value = "Existing user text";
    mockNav.promptParam = "Create Google Ads strategy";
    const { rerender } = render(<Harness />);

    act(() => {
      rs.advanceTimersByTime(120);
    });
    mockToast.mock.calls[0]?.[1]?.action?.onClick();
    expect(mockComposer.setInput).toHaveBeenCalledWith(
      "Create Google Ads strategy",
    );

    mockComposer.setInput.mockClear();
    mockToast.mockClear();
    mockComposer.value = "Edited ads prompt";
    mockNav.promptParam = "Write local SEO blog";
    rerender(<Harness />);
    act(() => {
      rs.advanceTimersByTime(120);
    });
    mockToast.mock.calls[0]?.[1]?.cancel?.onClick();

    mockComposer.value = "";
    rerender(<Harness />);
    act(() => {
      rs.advanceTimersByTime(120);
    });
    expect(mockComposer.setInput).not.toHaveBeenCalled();
  });
});
