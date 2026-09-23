import type { Message } from "@langchain/langgraph-sdk";
import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import {
  act,
  cleanup,
  render,
  renderHook,
  screen,
} from "@testing-library/react";
import type { ReactElement } from "react";

import { MessageGroup } from "@/components/workspace/messages/message-group";
import { RunActivity } from "@/components/workspace/messages/run-duration";
import {
  advanceDeepReasoningTracker,
  DeepReasoning,
  DeepReasoningContext,
  DeepReasoningStatus,
  initialDeepReasoningTracker,
  isDeepReasoningRun,
  useDeepReasoningTracker,
  type DeepReasoningTracker,
} from "@/components/workspace/messages/ultra-thinking";
import styles from "@/components/workspace/messages/ultra-thinking.module.css";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";

const appearance = rs.hoisted(() => ({
  value: {
    preferences: {
      treatment: "paper" as const,
      motion: true,
      logo: null,
      label: "",
    },
    reducedMotion: false,
    visible: true,
  },
}));

rs.mock("@/components/workspace/command-center/appearance-provider", () => ({
  useWorkspaceAppearance: () => appearance.value,
}));

rs.mock("@/components/workspace/artifacts", () => ({
  useArtifacts: () => ({
    artifacts: [],
    setArtifacts: () => undefined,
    selectedArtifact: null,
    autoSelect: false,
    select: () => undefined,
    deselect: () => undefined,
    open: false,
    autoOpen: false,
    setOpen: () => undefined,
  }),
}));

rs.mock("@/components/workspace/messages/markdown-content", () => ({
  MarkdownContent: () => null,
}));

const REASONING =
  "Goal: September report for Kestrel Roofing.\ncost_per_booked = 2610 / 31 = 84.19, down 29%.";
const THINKING_MODEL = {
  supports_thinking: true,
  supports_reasoning_effort: true,
};

const human = {
  id: "human-1",
  type: "human",
  content: "Plan the client report.",
} as Message;

function reasoningMessage(id: string, extra: Partial<Message> = {}) {
  return {
    id,
    type: "ai",
    content: "",
    additional_kwargs: { reasoning_content: REASONING },
    ...extra,
  } as Message;
}

function withI18n(ui: ReactElement) {
  return (
    <I18nContext.Provider
      value={{ locale: "en-US", setLocale: () => undefined, t: enUS }}
    >
      {ui}
    </I18nContext.Provider>
  );
}

/** Text a screen reader can reach: every text node outside aria-hidden. */
function accessibleText(root: Node) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let text = "";
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    if (!node.parentElement?.closest('[aria-hidden="true"]')) {
      text += node.nodeValue;
    }
  }
  return text;
}

function occurrences(haystack: string | null, needle: string) {
  return (haystack ?? "").split(needle).length - 1;
}

function motion(allowed: { motion?: boolean; reducedMotion?: boolean }) {
  appearance.value = {
    ...appearance.value,
    preferences: {
      ...appearance.value.preferences,
      motion: allowed.motion ?? true,
    },
    reducedMotion: allowed.reducedMotion ?? false,
  };
}

beforeEach(() => motion({}));

afterEach(() => {
  cleanup();
  rs.useRealTimers();
  rs.restoreAllMocks();
});

describe("isDeepReasoningRun", () => {
  it("is on for Ultra or a high/xhigh effort the model can take", () => {
    expect(isDeepReasoningRun({ mode: "ultra" }, THINKING_MODEL)).toBe(true);
    expect(
      isDeepReasoningRun(
        { mode: "pro", reasoning_effort: "high" },
        THINKING_MODEL,
      ),
    ).toBe(true);
    expect(
      isDeepReasoningRun(
        { mode: "thinking", reasoning_effort: "xhigh" },
        THINKING_MODEL,
      ),
    ).toBe(true);
    // Ultra defaults its effort to high, as buildRunContext does.
    expect(
      isDeepReasoningRun(
        { mode: "ultra" },
        { supports_reasoning_effort: true },
      ),
    ).toBe(true);
  });

  it("is off for lower efforts, flash, and models that cannot reason", () => {
    expect(
      isDeepReasoningRun(
        { mode: "pro", reasoning_effort: "medium" },
        THINKING_MODEL,
      ),
    ).toBe(false);
    expect(
      isDeepReasoningRun(
        { mode: "thinking", reasoning_effort: "low" },
        THINKING_MODEL,
      ),
    ).toBe(false);
    // Flash turns thinking off whatever effort was left in settings.
    expect(
      isDeepReasoningRun(
        { mode: "flash", reasoning_effort: "high" },
        THINKING_MODEL,
      ),
    ).toBe(false);
    // Ultra stays selectable on a non-thinking model for delegation only.
    expect(
      isDeepReasoningRun(
        { mode: "ultra" },
        { supports_thinking: false, supports_reasoning_effort: false },
      ),
    ).toBe(false);
    // The Gateway drops an effort the model does not take.
    expect(
      isDeepReasoningRun(
        { mode: "pro", reasoning_effort: "high" },
        { supports_thinking: true },
      ),
    ).toBe(false);
    expect(isDeepReasoningRun({ mode: "ultra" }, undefined)).toBe(false);
  });
});

describe("useDeepReasoningTracker", () => {
  function track(initialProps: {
    messages: Message[];
    isLoading: boolean;
    deep: boolean;
  }) {
    return renderHook(
      ({ messages, isLoading, deep }) =>
        useDeepReasoningTracker(messages, isLoading, deep),
      { initialProps },
    );
  }

  it("is live only while a deep run streams reasoning", () => {
    const { result, rerender } = track({
      messages: [human, reasoningMessage("ai-1")],
      isLoading: false,
      deep: true,
    });
    // Never on idle, even over a message that has reasoning.
    expect(result.current.liveId).toBeNull();

    rerender({ messages: [human], isLoading: true, deep: true });
    expect(result.current.liveId).toBeNull();

    rerender({
      messages: [human, reasoningMessage("ai-2")],
      isLoading: true,
      deep: true,
    });
    expect(result.current.liveId).toBe("ai-2");
    expect(result.current.joltId).toBe("ai-2");
    const live = result.current;

    // More reasoning streams in: the state object does not churn per chunk.
    rerender({
      messages: [
        human,
        reasoningMessage("ai-2", {
          additional_kwargs: { reasoning_content: `${REASONING} More.` },
        }),
      ],
      isLoading: true,
      deep: true,
    });
    expect(result.current).toBe(live);

    // The answer begins: reasoning has ended and leaves a receipt.
    rerender({
      messages: [
        human,
        reasoningMessage("ai-2", { content: "Here is the plan." }),
      ],
      isLoading: true,
      deep: true,
    });
    expect(result.current.liveId).toBeNull();
    expect(result.current.receipts.has("ai-2")).toBe(true);

    rerender({
      messages: [
        human,
        reasoningMessage("ai-2", { content: "Here is the plan." }),
      ],
      isLoading: false,
      deep: true,
    });
    expect(result.current.liveId).toBeNull();
  });

  it("ends a live phase when the model calls a tool", () => {
    const { result, rerender } = track({
      messages: [human],
      isLoading: false,
      deep: true,
    });
    rerender({
      messages: [human, reasoningMessage("ai-3")],
      isLoading: true,
      deep: true,
    });
    expect(result.current.liveId).toBe("ai-3");
    rerender({
      messages: [
        human,
        reasoningMessage("ai-3", {
          tool_calls: [{ id: "call-1", name: "read_file", args: {} }],
        } as Partial<Message>),
      ],
      isLoading: true,
      deep: true,
    });
    expect(result.current.liveId).toBeNull();
  });

  it("stays off for a run that is not deep", () => {
    const { result, rerender } = track({
      messages: [human],
      isLoading: false,
      deep: false,
    });
    rerender({
      messages: [human, reasoningMessage("ai-4")],
      isLoading: true,
      deep: false,
    });
    expect(result.current.liveId).toBeNull();
    expect(result.current.receipts.size).toBe(0);
  });

  it("reads the setting when the run starts, not mid-run", () => {
    const { result, rerender } = track({
      messages: [human],
      isLoading: false,
      deep: false,
    });
    rerender({ messages: [human], isLoading: true, deep: false });
    // Switching the composer to Ultra mid-run does not restyle this run.
    rerender({
      messages: [human, reasoningMessage("ai-5")],
      isLoading: true,
      deep: true,
    });
    expect(result.current.liveId).toBeNull();

    rerender({
      messages: [human, reasoningMessage("ai-5", { content: "Done." })],
      isLoading: false,
      deep: true,
    });
    rerender({
      messages: [human, reasoningMessage("ai-6")],
      isLoading: true,
      deep: true,
    });
    expect(result.current.liveId).toBe("ai-6");
  });

  it("times the receipt from the live start and jolts once per run", () => {
    let state = initialDeepReasoningTracker([human], false, true);
    state = advanceDeepReasoningTracker(state, [human], true, true, () => 0);
    state = advanceDeepReasoningTracker(
      state,
      [human, reasoningMessage("ai-7")],
      true,
      true,
      () => 1_000,
    );
    state = advanceDeepReasoningTracker(
      state,
      [
        human,
        reasoningMessage("ai-7", {
          tool_calls: [{ id: "call-1", name: "read_file", args: {} }],
        } as Partial<Message>),
      ],
      true,
      true,
      () => 8_400,
    );
    expect(state.receipts.get("ai-7")).toBe(7);

    // A second reasoning phase in the same run gets no second jolt.
    state = advanceDeepReasoningTracker(
      state,
      [human, reasoningMessage("ai-8")],
      true,
      true,
      () => 9_000,
    );
    expect(state.liveId).toBe("ai-8");
    expect(state.joltId).toBe("ai-7");
  });

  it("arriving mid-run is not a start: no jolt, and an unknown duration", () => {
    let state = initialDeepReasoningTracker(
      [human, reasoningMessage("ai-9")],
      true,
      true,
    );
    expect(state.liveId).toBe("ai-9");
    expect(state.joltId).toBeNull();
    state = advanceDeepReasoningTracker(
      state,
      [human, reasoningMessage("ai-9", { content: "Answer." })],
      true,
      true,
    );
    expect(state.receipts.get("ai-9")).toBeNull();
  });
});

describe("DeepReasoning", () => {
  it("streams real text once in the accessibility tree; print layers are hidden duplicates", () => {
    const { container } = render(
      withI18n(
        <DeepReasoning
          messageId="block-a11y"
          reasoning={REASONING}
          live
          seconds={null}
        />,
      ),
    );
    const block = container.querySelector("details")!;
    expect(block.open).toBe(true);
    expect(block.dataset.phase).toBe("live");
    expect(block.dataset.motion).toBe("on");
    expect(accessibleText(block)).toContain("Thinking deeply");
    expect(occurrences(accessibleText(block), REASONING)).toBe(1);
    // The cyan drum duplicates the text, but only as aria-hidden print.
    expect(occurrences(block.textContent, REASONING)).toBe(2);
    expect(
      block.querySelector(`.${styles.ghost}`)?.getAttribute("aria-hidden"),
    ).toBe("true");
    expect(
      block.querySelector(`.${styles.rain}`)?.getAttribute("aria-hidden"),
    ).toBe("true");
    // Labels across the view shimmer only while it streams.
    expect(document.documentElement.classList.contains(styles.live!)).toBe(
      true,
    );
    cleanup();
    expect(document.documentElement.classList.contains(styles.live!)).toBe(
      false,
    );
  });

  for (const [name, setting] of [
    ["reduced motion", { reducedMotion: true }],
    ["the appearance motion switch off", { motion: false }],
  ] as const) {
    it(`under ${name}: a static label, a plain block, no jolt`, () => {
      motion(setting);
      const { container } = render(
        withI18n(
          <DeepReasoning
            messageId={`block-static-${name}`}
            reasoning={REASONING}
            live
            jolt
            seconds={null}
          />,
        ),
      );
      const block = container.querySelector("details")!;
      expect(block.dataset.motion).toBe("off");
      expect(screen.getByText("Thinking deeply")).toBeTruthy();
      expect(occurrences(block.textContent, REASONING)).toBe(1);
      for (const layer of [
        styles.ghost,
        styles.titleGhost,
        styles.rain,
        styles.sweep,
        styles.hot,
        styles.caret,
      ]) {
        expect(block.querySelector(`.${layer}`)).toBeNull();
      }
      expect(document.querySelector(`.${styles.overclock}`)).toBeNull();
      expect(document.documentElement.classList.contains(styles.live!)).toBe(
        false,
      );
    });
  }

  it("settles into a calm block with a Thought for receipt", () => {
    const { container, rerender } = render(
      withI18n(
        <DeepReasoning
          messageId="block-settled"
          reasoning={REASONING}
          live={false}
          seconds={7}
        />,
      ),
    );
    const block = container.querySelector("details")!;
    expect(block.dataset.phase).toBe("settled");
    expect(block.dataset.motion).toBe("off");
    expect(block.open).toBe(false);
    const summary = block.querySelector("summary")!;
    expect(accessibleText(summary)).toBe("ReasoningThought for 7s");
    expect(block.querySelector(`.${styles.squares}`)).toBeNull();
    expect(occurrences(accessibleText(block), REASONING)).toBe(1);

    // An unknown duration is left out, never shown as 0.
    rerender(
      withI18n(
        <DeepReasoning
          messageId="block-settled"
          reasoning={REASONING}
          live={false}
          seconds={null}
        />,
      ),
    );
    expect(block.textContent).not.toContain("Thought for");
  });

  describe("the overclock jolt", () => {
    const rect = {
      x: 20,
      y: 40,
      left: 20,
      top: 40,
      width: 90,
      height: 18,
      right: 110,
      bottom: 58,
      toJSON: () => ({}),
    } as DOMRect;
    let label: HTMLElement;
    let restore: () => void;

    beforeEach(() => {
      label = document.createElement("h2");
      label.textContent = "Kestrel September report";
      document.body.append(label);
      const rangeRect = Object.getOwnPropertyDescriptor(
        Range.prototype,
        "getBoundingClientRect",
      );
      const pointHit = Object.getOwnPropertyDescriptor(
        document,
        "elementFromPoint",
      );
      Object.defineProperty(Range.prototype, "getBoundingClientRect", {
        configurable: true,
        value: () => rect,
      });
      Object.defineProperty(document, "elementFromPoint", {
        configurable: true,
        value: () => label,
      });
      rs.spyOn(Element.prototype, "getBoundingClientRect").mockReturnValue(
        rect,
      );
      restore = () => {
        label.remove();
        if (rangeRect) {
          Object.defineProperty(
            Range.prototype,
            "getBoundingClientRect",
            rangeRect,
          );
        }
        if (pointHit) {
          Object.defineProperty(document, "elementFromPoint", pointHit);
        } else {
          delete (document as { elementFromPoint?: unknown }).elementFromPoint;
        }
      };
      rs.useFakeTimers();
    });

    afterEach(() => restore());

    it("scrambles an aria-hidden overlay once, never the page's own text, and clears in 520ms", () => {
      const view = render(
        withI18n(
          <DeepReasoning
            messageId="block-jolt"
            reasoning={REASONING}
            live
            jolt
            seconds={null}
          />,
        ),
      );
      const overlay = document.querySelector<HTMLElement>(
        `.${styles.overclock}`,
      );
      expect(overlay?.getAttribute("aria-hidden")).toBe("true");
      expect(overlay?.children).toHaveLength(3);
      // The last frame resolves to the real words.
      expect(overlay?.lastElementChild?.textContent).toBe(
        "KestrelSeptemberreport",
      );
      expect(document.documentElement.classList.contains(styles.jolting!)).toBe(
        true,
      );
      // The page's text nodes, and the reasoning, are never rewritten.
      expect(label.textContent).toBe("Kestrel September report");
      expect(overlay?.textContent).not.toContain("Goal:");

      act(() => {
        rs.advanceTimersByTime(520);
      });
      expect(document.querySelector(`.${styles.overclock}`)).toBeNull();
      expect(document.documentElement.classList.contains(styles.jolting!)).toBe(
        false,
      );

      // Remounted while still live (scrolled away and back): no second jolt.
      view.unmount();
      render(
        withI18n(
          <DeepReasoning
            messageId="block-jolt"
            reasoning={REASONING}
            live
            jolt
            seconds={null}
          />,
        ),
      );
      expect(document.querySelector(`.${styles.overclock}`)).toBeNull();
    });

    it("stops at once when the reasoning ends mid-jolt", () => {
      const view = render(
        withI18n(
          <DeepReasoning
            messageId="block-jolt-cut"
            reasoning={REASONING}
            live
            jolt
            seconds={null}
          />,
        ),
      );
      expect(document.querySelector(`.${styles.overclock}`)).not.toBeNull();
      view.rerender(
        withI18n(
          <DeepReasoning
            messageId="block-jolt-cut"
            reasoning={REASONING}
            live={false}
            seconds={1}
          />,
        ),
      );
      expect(document.querySelector(`.${styles.overclock}`)).toBeNull();
      expect(document.documentElement.classList.contains(styles.jolting!)).toBe(
        false,
      );
    });
  });
});

describe("DeepReasoningStatus", () => {
  it("announces Thinking deeply once per run, not per phase or token", () => {
    const idle = initialDeepReasoningTracker([], false, true);
    const { rerender } = render(withI18n(<DeepReasoningStatus state={idle} />));
    const status = screen.getByRole("status");
    expect(status.textContent).toBe("");

    const running: DeepReasoningTracker = {
      ...idle,
      loading: true,
      deep: true,
      liveId: "ai-1",
      started: true,
    };
    rerender(withI18n(<DeepReasoningStatus state={running} />));
    expect(status.textContent).toBe("Thinking deeply");

    // Between reasoning phases the text holds, so nothing re-announces.
    rerender(
      withI18n(<DeepReasoningStatus state={{ ...running, liveId: null }} />),
    );
    expect(status.textContent).toBe("Thinking deeply");

    rerender(
      withI18n(
        <DeepReasoningStatus
          state={{ ...running, loading: false, liveId: null }}
        />,
      ),
    );
    expect(status.textContent).toBe("");
  });
});

describe("MessageGroup with deep reasoning", () => {
  const live: DeepReasoningTracker = {
    ...initialDeepReasoningTracker([], false, true),
    loading: true,
    deep: true,
    liveId: "ai-group",
    started: true,
  };

  it("streams the tracked message in the deep block instead of the Thinking row", () => {
    const { container } = render(
      withI18n(
        <DeepReasoningContext.Provider value={live}>
          <MessageGroup messages={[reasoningMessage("ai-group")]} isLoading />
        </DeepReasoningContext.Provider>,
      ),
    );
    const block =
      container.querySelector<HTMLDetailsElement>("[data-ultra-block]");
    expect(block?.dataset.phase).toBe("live");
    expect(accessibleText(container)).toContain("Thinking deeply");
    expect(occurrences(accessibleText(container), REASONING)).toBe(1);
    expect(screen.queryByText("Thinking")).toBeNull();
  });

  it("keeps the plain Thinking row for any other message", () => {
    const { container } = render(
      withI18n(
        <DeepReasoningContext.Provider value={live}>
          <MessageGroup messages={[reasoningMessage("ai-other")]} isLoading />
        </DeepReasoningContext.Provider>,
      ),
    );
    expect(screen.getByText("Thinking")).toBeTruthy();
    expect(container.querySelector("[data-ultra-block]")).toBeNull();
  });
});

describe("RunActivity", () => {
  it("shows three stepped squares and the word, without the shimmer", () => {
    render(withI18n(<RunActivity startTime={null} />));
    const activity = screen.getByTestId("run-activity");
    expect(accessibleText(activity)).toBe("Working…");
    const squares = activity.querySelector(`.${styles.squares}`);
    expect(squares?.getAttribute("aria-hidden")).toBe("true");
    expect(squares?.children).toHaveLength(3);
    expect(activity.querySelector(".bg-clip-text")).toBeNull();
  });
});
