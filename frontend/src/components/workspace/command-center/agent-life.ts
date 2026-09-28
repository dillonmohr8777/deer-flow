import type { ConsoleRunItem } from "@/core/console/types";

/**
 * What an agent's avatar shows, read from its recorded runs. Five states,
 * one per real run status family (DESIGN.md, Motion item 7):
 *
 * - thinking: a run is recorded as pending (started, no work picked up yet)
 * - running: a run is recorded as running
 * - done: the latest settled run succeeded; `at` dates the stamp
 * - failed: the latest settled run errored or timed out
 * - idle: no runs, or the latest one was interrupted (a stop is not a failure)
 * - unknown: no run in a truncated page of history, so its latest run may be
 *   older than the page; drawn still, like idle, but never worded as idle
 */
export type AgentLifeState =
  | "idle"
  | "unknown"
  | "thinking"
  | "running"
  | "done"
  | "failed";

export type AgentLife = { state: AgentLifeState; at?: string | null };

const IDLE: AgentLife = { state: "idle" };

function settledAt(run: Pick<ConsoleRunItem, "created_at" | "updated_at">) {
  return Date.parse(run.updated_at ?? run.created_at ?? "") || 0;
}

export function agentLife(
  runs: readonly Pick<
    ConsoleRunItem,
    "assistant_id" | "status" | "created_at" | "updated_at"
  >[],
  name: string,
  /** True when `runs` is one page of a longer history (`has_more`). */
  truncated = false,
): AgentLife {
  const own = runs.filter((run) => run.assistant_id === name);
  if (own.some((run) => run.status === "running")) return { state: "running" };
  if (own.some((run) => run.status === "pending")) return { state: "thinking" };
  const latest = own.reduce<(typeof own)[number] | null>(
    (best, run) => (!best || settledAt(run) > settledAt(best) ? run : best),
    null,
  );
  // Missing from a partial page is unknown, not idle: the latest run may
  // have failed just beyond it.
  if (!latest) return truncated ? { state: "unknown" } : IDLE;
  const at = latest.updated_at ?? latest.created_at;
  if (latest.status === "success") return { state: "done", at };
  if (latest.status === "error" || latest.status === "timeout")
    return { state: "failed", at };
  return IDLE;
}

export function agentLives(
  runs: Parameters<typeof agentLife>[0],
  names: readonly string[],
  truncated = false,
): Record<string, AgentLife> {
  return Object.fromEntries(
    names.map((name) => [name, agentLife(runs, name, truncated)]),
  );
}

/** "Sep 24": the stamp's date, in the viewer's time zone. */
export function stampDate(at: string | null | undefined): string | null {
  const time = Date.parse(at ?? "");
  if (!time) return null;
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
  }).format(time);
}

export function agentLifeLabel(life: AgentLife): string {
  const date = stampDate(life.at);
  switch (life.state) {
    case "thinking":
      return "Thinking";
    case "running":
      return "Running";
    case "done":
      return date ? `Done ${date}` : "Done";
    case "failed":
      return date ? `Failed ${date}` : "Last run failed";
    case "unknown":
      return "No recent run";
    default:
      return "Idle";
  }
}
