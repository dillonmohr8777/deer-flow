const RETRY_DELAYS_MS = [1_000, 2_000] as const;
const MAX_ATTEMPTS = RETRY_DELAYS_MS.length + 1;

export type ActiveRunRejoinState = Readonly<
  | {
      phase: "unavailable";
      threadId: string | null;
      runId: string | null;
      attempts: 0;
    }
  | {
      phase: "ready" | "joining" | "backoff" | "settled" | "exhausted";
      threadId: string;
      runId: string;
      attempts: number;
    }
>;

export function createActiveRunRejoinState(
  threadId: string | null = null,
  runId: string | null = null,
): ActiveRunRejoinState {
  return threadId && runId
    ? { phase: "ready", threadId, runId, attempts: 0 }
    : { phase: "unavailable", threadId, runId, attempts: 0 };
}

/** State belongs to one discovered thread/run; timers and SDK calls stay in the hook. */
export function transitionActiveRunRejoin(
  state: ActiveRunRejoinState,
  event: "start" | "failed" | "retry" | "finished",
): ActiveRunRejoinState {
  if (state.phase === "unavailable") return state;
  switch (event) {
    case "start":
      if (state.phase !== "ready" || state.attempts >= MAX_ATTEMPTS)
        return state;
      return { ...state, phase: "joining", attempts: state.attempts + 1 };
    case "failed":
      if (state.phase !== "joining") return state;
      return {
        ...state,
        phase: state.attempts < MAX_ATTEMPTS ? "backoff" : "exhausted",
      };
    case "retry":
      if (state.phase !== "backoff") return state;
      return { ...state, phase: "ready" };
    case "finished":
      // Completion can arrive after the transport failed and before its
      // queued retry. Only an attempted recovery owns this finish.
      if (state.attempts === 0 || state.phase === "settled") return state;
      return { ...state, phase: "settled" };
  }
}

export function activeRunRejoinRetryDelay(
  state: ActiveRunRejoinState,
): number | null {
  return state.phase === "backoff"
    ? (RETRY_DELAYS_MS[state.attempts - 1] ?? null)
    : null;
}
