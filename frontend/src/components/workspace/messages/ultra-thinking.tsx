"use client";

import type { Message } from "@langchain/langgraph-sdk";
import { ChevronDownIcon } from "lucide-react";
import { createContext, useState } from "react";

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
 *
 * 2026-10-22 (Dillon: "no weird static ... no choppiness"): the glitch
 * motion is gone (the screen-wide overclock scramble, the label jitter and
 * the misregistered ghost text). Only the reasoning text prints in, with a
 * soft caret.
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
    };
  }
  if (!state.receipts.has(messageId)) {
    return null;
  }
  return {
    messageId,
    live: false,
    seconds: state.receipts.get(messageId) ?? null,
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

export function DeepReasoning({
  messageId: _messageId,
  reasoning,
  live,
  seconds,
  framed = true,
}: {
  messageId: string;
  reasoning: string;
  live: boolean;
  seconds: number | null;
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
        </span>
        {duration && (
          <span className={styles.receipt} data-receipt="">
            {t.runDuration.thoughtFor(duration)}
          </span>
        )}
        <ChevronDownIcon className={styles.chevron} aria-hidden="true" />
      </summary>
      <div className={styles.body}>
        <div className={styles.print}>
          <div className={styles.stack}>
            <p className={styles.text}>
              <Ink text={reasoning} printing={motion} />
            </p>
          </div>
        </div>
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
