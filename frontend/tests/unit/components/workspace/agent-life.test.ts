import { describe, expect, it } from "@rstest/core";

import {
  agentLife,
  agentLifeLabel,
  agentLives,
} from "@/components/workspace/command-center/agent-life";

const run = (
  assistant_id: string | null,
  status: string,
  updated_at: string | null = "2026-09-24T14:00:00Z",
) => ({ assistant_id, status, created_at: updated_at, updated_at });

describe("agentLife", () => {
  it("is idle with no recorded runs", () => {
    expect(agentLife([], "dillon-growth")).toEqual({ state: "idle" });
    expect(
      agentLife([run("dillon-critic", "running")], "dillon-growth"),
    ).toEqual({ state: "idle" });
  });

  it("is thinking while a run is pending and running once one runs", () => {
    expect(
      agentLife([run("dillon-critic", "pending")], "dillon-critic").state,
    ).toBe("thinking");
    // Running wins over pending: one run is already at work.
    expect(
      agentLife(
        [run("dillon-critic", "pending"), run("dillon-critic", "running")],
        "dillon-critic",
      ).state,
    ).toBe("running");
    // Active work wins over any older settled run.
    expect(
      agentLife(
        [
          run("dillon-critic", "error", "2026-09-24T15:00:00Z"),
          run("dillon-critic", "pending", "2026-09-24T09:00:00Z"),
        ],
        "dillon-critic",
      ).state,
    ).toBe("thinking");
  });

  it("dates done and failed from the latest settled run", () => {
    expect(
      agentLife(
        [
          run("dillon-builder", "error", "2026-09-23T10:00:00Z"),
          run("dillon-builder", "success", "2026-09-24T10:00:00Z"),
        ],
        "dillon-builder",
      ),
    ).toEqual({ state: "done", at: "2026-09-24T10:00:00Z" });
    expect(
      agentLife(
        [
          run("dillon-builder", "success", "2026-09-23T10:00:00Z"),
          run("dillon-builder", "timeout", "2026-09-24T10:00:00Z"),
        ],
        "dillon-builder",
      ),
    ).toEqual({ state: "failed", at: "2026-09-24T10:00:00Z" });
  });

  it("treats an interrupted run as idle, not failed", () => {
    expect(
      agentLife([run("dillon-growth", "interrupted")], "dillon-growth"),
    ).toEqual({ state: "idle" });
  });

  it("keys every requested name", () => {
    const lives = agentLives(
      [run("dillon-growth", "success")],
      ["dillon-growth", "dillon-critic"],
    );
    expect(lives["dillon-growth"]?.state).toBe("done");
    expect(lives["dillon-critic"]?.state).toBe("idle");
  });
});

describe("agentLifeLabel", () => {
  it("puts every state into words, dated where it settled", () => {
    expect(agentLifeLabel({ state: "idle" })).toBe("Idle");
    expect(agentLifeLabel({ state: "thinking" })).toBe("Thinking");
    expect(agentLifeLabel({ state: "running" })).toBe("Running");
    expect(agentLifeLabel({ state: "done", at: "2026-09-24T12:00:00Z" })).toBe(
      "Done Sep 24",
    );
    expect(
      agentLifeLabel({ state: "failed", at: "2026-09-24T12:00:00Z" }),
    ).toBe("Failed Sep 24");
    // No date recorded: say so plainly rather than inventing one.
    expect(agentLifeLabel({ state: "done", at: null })).toBe("Done");
    expect(agentLifeLabel({ state: "failed" })).toBe("Last run failed");
  });
});
