"use client";

import type { Message } from "@langchain/langgraph-sdk";
import { ChevronDownIcon } from "lucide-react";
import { createContext, useEffect, useState } from "react";

import { brandMotionAllowed } from "@/components/workspace/command-center/appearance-preferences";
import { useWorkspaceAppearance } from "@/components/workspace/command-center/appearance-provider";
import { useI18n } from "@/core/i18n/hooks";
import { formatRunDuration } from "@/core/messages/run-duration";
import {
  extractContentFromMessage,
  hasReasoning,
  hasToolCalls,
  isHiddenFromUIMessage,
} from "@/core/messages/utils";
import type { Model } from "@/core/models/types";

import styles from "./ultra-thinking.module.css";

/*
 * "Ultra thinking": the reasoning block of a deep run while its reasoning
 * streams, then a calm settled block with a "Thought for Ns" receipt.
 * Approved prototype: block-shots/2026-09-22-design/acid (variants B and D).
 */

const DEEP_EFFORTS: ReadonlySet<string> = new Set(["high", "xhigh"]);

/**
 * Whether a run asks for deep reasoning its model can actually do: Ultra on a
 * thinking model, or a high/xhigh effort on a model that takes an effort.
 * Mirrors buildRunContext (core/threads/hooks.ts): flash turns thinking off,
 * and Ultra's effort defaults to high.
 */
export function isDeepReasoningRun(
  context: { mode?: string; reasoning_effort?: string },
  model?: Pick<Model, "supports_thinking" | "supports_reasoning_effort">,
): boolean {
  if (!model || context.mode === "flash") {
    return false;
  }
  const effort =
    context.reasoning_effort ?? (context.mode === "ultra" ? "high" : "");
  return (
    (context.mode === "ultra" && model.supports_thinking === true) ||
    (model.supports_reasoning_effort === true && DEEP_EFFORTS.has(effort))
  );
}

/**
 * The message whose reasoning is streaming right now: the newest visible
 * message, while it carries reasoning and nothing else yet. Answer text or a
 * tool call means its reasoning has ended.
 */
export function findLiveReasoningId(
  messages: readonly Message[],
): string | null {
  for (let index = messages.length - 1; index >= 0; index--) {
    const message = messages[index];
    if (!message || isHiddenFromUIMessage(message)) {
      continue;
    }
    return message.type === "ai" &&
      message.id &&
      hasReasoning(message) &&
      !hasToolCalls(message) &&
      extractContentFromMessage(message).length === 0
      ? message.id
      : null;
  }
  return null;
}

export type DeepReasoningTracker = {
  /** The thread is streaming a run. */
  loading: boolean;
  /** That run's own setting, captured when it started. */
  deep: boolean;
  /** The message whose deep reasoning is streaming now. */
  liveId: string | null;
  /** When liveId went live; null when it was already live at mount. */
  since: number | null;
  /** Settled deep reasoning this session: whole seconds, or null if unknown. */
  receipts: ReadonlyMap<string, number | null>;
  /** This run has streamed deep reasoning (drives the one announcement). */
  started: boolean;
  /** The one live start per run that gets the overclock jolt. */
  joltId: string | null;
  /** No jolt chosen yet for a run that began while this list was mounted. */
  joltArmed: boolean;
};

const NO_RECEIPTS: ReadonlyMap<string, number | null> = new Map();

export function initialDeepReasoningTracker(
  messages: readonly Message[],
  isLoading: boolean,
  deep: boolean,
): DeepReasoningTracker {
  const liveId = isLoading && deep ? findLiveReasoningId(messages) : null;
  return {
    loading: isLoading,
    deep: isLoading && deep,
    liveId,
    since: null,
    receipts: NO_RECEIPTS,
    started: liveId !== null,
    // Arriving mid-run (a reload, a thread switch) is not a start: no jolt.
    joltId: null,
    joltArmed: !isLoading,
  };
}

/** Pure step: returns `state` itself when nothing changed. */
export function advanceDeepReasoningTracker(
  state: DeepReasoningTracker,
  messages: readonly Message[],
  isLoading: boolean,
  deep: boolean,
  now: () => number = Date.now,
): DeepReasoningTracker {
  let next = state;
  if (isLoading !== next.loading) {
    next = isLoading
      ? {
          ...next,
          loading: true,
          deep,
          started: false,
          joltId: null,
          joltArmed: true,
        }
      : { ...next, loading: false };
  }
  const liveId =
    next.loading && next.deep ? findLiveReasoningId(messages) : null;
  if (liveId !== next.liveId) {
    const time = now();
    const receipts =
      next.liveId === null
        ? next.receipts
        : new Map(next.receipts).set(
            next.liveId,
            next.since === null ? null : Math.floor((time - next.since) / 1000),
          );
    next = {
      ...next,
      liveId,
      since: liveId === null ? null : time,
      receipts,
      started: next.started || liveId !== null,
      joltId: liveId !== null && next.joltArmed ? liveId : next.joltId,
      joltArmed: next.joltArmed && liveId === null,
    };
  }
  return next;
}

/**
 * Tracks deep reasoning across a thread's runs. The state object changes only
 * at a run edge or a reasoning start or end, never per streamed chunk, so its
 * context consumers re-render only then.
 */
export function useDeepReasoningTracker(
  messages: readonly Message[],
  isLoading: boolean,
  deep: boolean,
): DeepReasoningTracker {
  const [state, setState] = useState(() =>
    initialDeepReasoningTracker(messages, isLoading, deep),
  );
  // Adjusting state while rendering: the settled block replaces the live one
  // in the same commit, with no frame of plain reasoning in between.
  const next = advanceDeepReasoningTracker(state, messages, isLoading, deep);
  if (next !== state) {
    setState(next);
  }
  return next;
}

export const DeepReasoningContext = createContext<DeepReasoningTracker | null>(
  null,
);

/** Props for DeepReasoning when this message's reasoning is deep, else null. */
export function deepReasoningFor(
  state: DeepReasoningTracker | null,
  messageId: string | undefined,
) {
  if (!state || !messageId) {
    return null;
  }
  if (state.liveId === messageId) {
    return {
      messageId,
      live: true,
      seconds: null,
      jolt: state.joltId === messageId,
    };
  }
  if (!state.receipts.has(messageId)) {
    return null;
  }
  return {
    messageId,
    live: false,
    seconds: state.receipts.get(messageId) ?? null,
    jolt: false,
  };
}

/**
 * The one screen reader announcement per deep run, through a polite live
 * region that is always mounted: its text is set when the run's reasoning
 * first streams and holds until the run ends, so tokens never re-announce.
 */
export function DeepReasoningStatus({
  state,
}: {
  state: DeepReasoningTracker;
}) {
  const { t } = useI18n();
  return (
    <p className="sr-only" role="status" aria-live="polite">
      {state.loading && state.started ? t.runDuration.thinkingDeeply : ""}
    </p>
  );
}

// ponytail: per-tab memory of jolts already played, one id per deep run;
// keeps a remounted live block (scrolled away and back) from jolting twice.
const jolted = new Set<string>();

export function DeepReasoning({
  messageId,
  reasoning,
  live,
  seconds,
  jolt = false,
  framed = true,
}: {
  messageId: string;
  reasoning: string;
  live: boolean;
  seconds: number | null;
  jolt?: boolean;
  framed?: boolean;
}) {
  const { t } = useI18n();
  const { preferences, reducedMotion, visible } = useWorkspaceAppearance();
  const motion =
    live &&
    brandMotionAllowed({
      motion: preferences.motion && preferences.treatment !== "classic",
      reducedMotion,
      visible,
      inView: true,
    });

  useEffect(() => {
    if (!motion) {
      return;
    }
    const root = document.documentElement;
    root.classList.add(styles.live!);
    return () => root.classList.remove(styles.live!);
  }, [motion]);

  useEffect(() => {
    if (!motion || !jolt || jolted.has(messageId)) {
      return;
    }
    return overclock(() => jolted.add(messageId));
  }, [jolt, messageId, motion]);

  const duration =
    !live && seconds !== null
      ? formatRunDuration(seconds, t.runDuration)
      : null;

  return (
    <details
      className={styles.block}
      data-ultra-block=""
      data-phase={live ? "live" : "settled"}
      data-motion={motion ? "on" : "off"}
      data-framed={framed ? undefined : "false"}
      open={live}
    >
      <summary className={styles.head}>
        {live && <WorkingSquares />}
        <span className={styles.title}>
          <span>
            {live ? t.runDuration.thinkingDeeply : t.runDuration.reasoning}
          </span>
          {motion && (
            <span className={styles.titleGhost} aria-hidden="true">
              {t.runDuration.thinkingDeeply}
            </span>
          )}
        </span>
        {duration && (
          <span className={styles.receipt} data-receipt="">
            {t.runDuration.thoughtFor(duration)}
          </span>
        )}
        <ChevronDownIcon className={styles.chevron} aria-hidden="true" />
      </summary>
      <RegistrationMarks />
      {motion && <span className={styles.sweep} aria-hidden="true" />}
      <div className={styles.body}>
        <div className={styles.print}>
          <div className={styles.stack}>
            <p className={styles.text}>
              <Ink text={reasoning} printing={motion} />
            </p>
            {motion && (
              <p className={styles.ghost} aria-hidden="true">
                <Ink text={reasoning} printing />
              </p>
            )}
          </div>
        </div>
        {motion && <TokenRain text={reasoning} />}
      </div>
    </details>
  );
}

/** The motion vocabulary's working state: three squares ticking in steps. */
export function WorkingSquares() {
  return (
    <span className={styles.squares} aria-hidden="true">
      <span />
      <span />
      <span />
    </span>
  );
}

/** Real text; while printing, its newest word in inverse and a block caret. */
function Ink({ text, printing }: { text: string; printing: boolean }) {
  if (!printing) {
    return text;
  }
  const tail = text.slice(-200);
  const lastWord = /\S+\s*$/.exec(tail);
  const cut = lastWord
    ? text.length - tail.length + lastWord.index
    : text.length;
  return (
    <>
      {text.slice(0, cut)}
      <span className={styles.hot}>{text.slice(cut)}</span>
      <span className={styles.caret} aria-hidden="true" />
    </>
  );
}

/**
 * The newest words, newest first, in two columns. A word's column comes from
 * its offset in the text, so words keep their column as more stream in.
 */
export function tokenRainColumns(text: string, limit = 48) {
  const base = Math.max(0, text.length - 480);
  const columns: { at: number; word: string }[][] = [[], []];
  const words = [...text.slice(base).matchAll(/\S+/g)];
  for (
    let index = words.length - 1, taken = 0;
    index >= 0 && taken < limit;
    index--, taken++
  ) {
    const match = words[index]!;
    if (index === 0 && base > 0) {
      break; // may be the cut-off tail of a longer word
    }
    const at = base + match.index;
    columns[at % 2]!.push({ at, word: match[0].slice(0, 12) });
  }
  return columns;
}

function TokenRain({ text }: { text: string }) {
  return (
    <div className={styles.rain} aria-hidden="true">
      {tokenRainColumns(text).map((words, column) => (
        <div key={column}>
          {words.map(({ at, word }) => (
            <span key={at}>{word}</span>
          ))}
        </div>
      ))}
    </div>
  );
}

const CORNERS = ["tl", "tr", "bl", "br"] as const;

function RegistrationMarks() {
  return CORNERS.map((corner) => (
    <svg
      key={corner}
      className={styles.reg}
      data-corner={corner}
      viewBox="0 0 16 16"
      aria-hidden="true"
      focusable="false"
    >
      {[styles.regC, styles.regB].map((plate) => (
        <g key={plate} className={plate}>
          <circle cx="8" cy="8" r="3.5" />
          <path d="M8 1v14M1 8h14" />
        </g>
      ))}
    </svg>
  ));
}

const JOLT_MS = 520;
const MAX_WORDS = 600;
const MAX_MEASURES = 4000;
const GLYPHS =
  "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz0123456789#%&*+=<>/[]{}";
const UNTOUCHED =
  "[data-ultra-block], input, textarea, select, [contenteditable]";

type OverclockWord = {
  text: string;
  rect: DOMRect;
  style: CSSStyleDeclaration;
};

/**
 * Variant D's one-shot overclock: every visible word scrambles, misregisters
 * and resolves to itself in 520ms. The page's own text nodes are never
 * rewritten: an aria-hidden overlay carries three frames of glyphs while CSS
 * hides the real glyphs by fill colour, so nothing reflows. Words are
 * measured once; CSS steps the frames on opacity and transform. Returns a
 * cancel that removes everything at once.
 */
export function overclock(onFinish?: () => void): () => void {
  const words = visibleWords();
  const overlay = document.createElement("div");
  overlay.className = styles.overclock!;
  overlay.setAttribute("aria-hidden", "true");
  for (const [frameClass, scramble] of [
    [styles.frameA, "all"],
    [styles.frameB, "some"],
    [styles.frameC, "none"],
  ] as const) {
    const frame = document.createElement("div");
    frame.className = frameClass!;
    for (const word of words) {
      frame.append(glyphSpan(word, scramble));
    }
    overlay.append(frame);
  }
  const root = document.documentElement;
  document.body.append(overlay);
  root.classList.add(styles.jolting!);
  let done = false;
  const stop = () => {
    if (done) {
      return;
    }
    done = true;
    window.clearTimeout(timer);
    overlay.remove();
    root.classList.remove(styles.jolting!);
  };
  const timer = window.setTimeout(() => {
    stop();
    onFinish?.();
  }, JOLT_MS);
  return stop;
}

function glyphSpan(
  { text, rect, style }: OverclockWord,
  scramble: "all" | "some" | "none",
) {
  const span = document.createElement("span");
  const characters = [...text];
  span.textContent =
    scramble === "none"
      ? text
      : characters
          .map((character, index) =>
            /[\p{L}\p{N}]/u.test(character) &&
            (scramble === "all" || Math.random() < index / characters.length)
              ? GLYPHS[Math.floor(Math.random() * GLYPHS.length)]
              : character,
          )
          .join("");
  Object.assign(span.style, {
    left: `${rect.left}px`,
    top: `${rect.top}px`,
    lineHeight: `${rect.height}px`,
    fontFamily: style.fontFamily,
    fontSize: style.fontSize,
    fontStyle: style.fontStyle,
    fontWeight: style.fontWeight,
    letterSpacing: style.letterSpacing,
    textTransform: style.textTransform,
    ...(scramble === "none" ? {} : { color: style.color }),
  });
  return span;
}

/** Words drawn on screen right now, topmost only, capped. */
function visibleWords(): OverclockWord[] {
  const words: OverclockWord[] = [];
  const range = document.createRange();
  const computed = new Map<Element, CSSStyleDeclaration | null>();
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let measures = 0;
  for (
    let node = walker.nextNode();
    node && words.length < MAX_WORDS && measures < MAX_MEASURES;
    node = walker.nextNode()
  ) {
    const parent = node.parentElement;
    const text = node.nodeValue ?? "";
    if (!parent || !/\S/.test(text)) {
      continue;
    }
    let style = computed.get(parent);
    if (style === undefined) {
      style = onScreen(parent) ? getComputedStyle(parent) : null;
      computed.set(parent, style);
    }
    if (!style) {
      continue;
    }
    for (const match of text.matchAll(/\S+/g)) {
      range.setStart(node, match.index);
      range.setEnd(node, match.index + match[0].length);
      const rect = range.getBoundingClientRect();
      measures++;
      if (rect.top > window.innerHeight || words.length >= MAX_WORDS) {
        break; // the rest of this node is below the fold
      }
      if (rect.width > 0 && drawnOnTop(parent, rect)) {
        words.push({ text: match[0], rect, style });
      }
    }
  }
  return words;
}

function onScreen(element: Element) {
  if (element.closest(UNTOUCHED)) {
    return false;
  }
  const box = element.getBoundingClientRect();
  return (
    box.bottom > 0 &&
    box.right > 0 &&
    box.top < window.innerHeight &&
    box.left < window.innerWidth
  );
}

/** A word under a header or a sheet is not visible, so it does not jolt. */
function drawnOnTop(parent: Element, rect: DOMRect) {
  const hit = document.elementFromPoint(
    rect.left + rect.width / 2,
    rect.top + rect.height / 2,
  );
  return (
    hit !== null &&
    (hit === parent || parent.contains(hit) || hit.contains(parent))
  );
}
