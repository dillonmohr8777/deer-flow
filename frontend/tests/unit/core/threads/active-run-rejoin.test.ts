import { expect, test } from "@rstest/core";

import {
  activeRunRejoinRetryDelay,
  createActiveRunRejoinState,
  transitionActiveRunRejoin,
} from "@/core/threads/active-run-rejoin";

test("bounds recovery to three attempts with the existing backoff", () => {
  let state = createActiveRunRejoinState("thread", "run");
  for (const [index, delay] of [1000, 2000, null].entries()) {
    state = transitionActiveRunRejoin(state, "start");
    expect(state.phase).toBe("joining");
    expect(state.attempts).toBe(index + 1);
    // A duplicate start cannot consume another attempt.
    expect(transitionActiveRunRejoin(state, "start")).toBe(state);
    state = transitionActiveRunRejoin(state, "failed");
    expect(activeRunRejoinRetryDelay(state)).toBe(delay);
    state = transitionActiveRunRejoin(state, "retry");
  }
  expect(state.phase).toBe("exhausted");
  expect(transitionActiveRunRejoin(state, "start")).toBe(state);
  expect(transitionActiveRunRejoin(state, "failed")).toBe(state);
});

test.each(["joining", "backoff", "ready", "exhausted"])(
  "completion settles an owned recovery in %s",
  (phase) => {
    let state = createActiveRunRejoinState("thread", "run");
    state = transitionActiveRunRejoin(state, "start");
    for (let step = 0; state.phase !== phase && step < 8; step += 1) {
      state = transitionActiveRunRejoin(
        state,
        state.phase === "joining"
          ? "failed"
          : state.phase === "backoff"
            ? "retry"
            : "start",
      );
    }
    expect(state.phase).toBe(phase);
    state = transitionActiveRunRejoin(state, "finished");
    expect(state.phase).toBe("settled");
    for (const event of ["start", "failed", "retry", "finished"] as const) {
      expect(transitionActiveRunRejoin(state, event)).toBe(state);
    }
    expect(activeRunRejoinRetryDelay(state)).toBeNull();
  },
);

test("unresolved or unattempted discovery does not own a completion", () => {
  for (const state of [
    createActiveRunRejoinState(),
    createActiveRunRejoinState("thread", null),
    createActiveRunRejoinState("thread", "run"),
  ]) {
    expect(transitionActiveRunRejoin(state, "finished")).toBe(state);
    expect(activeRunRejoinRetryDelay(state)).toBeNull();
  }
});

test("a new run gets a fresh independent recovery budget", () => {
  const old = transitionActiveRunRejoin(
    transitionActiveRunRejoin(
      createActiveRunRejoinState("thread", "old"),
      "start",
    ),
    "finished",
  );
  const next = createActiveRunRejoinState("thread", "next");
  expect(old.phase).toBe("settled");
  expect(next).toEqual({
    phase: "ready",
    threadId: "thread",
    runId: "next",
    attempts: 0,
  });
});
