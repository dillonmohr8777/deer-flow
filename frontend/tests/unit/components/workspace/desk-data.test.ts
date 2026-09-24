import { describe, expect, it } from "@rstest/core";

import {
  groupByDepartment,
  receiptPath,
  recentOutputs,
  summarizeTasks,
  tasksOfBindings,
  tasksOfTemplate,
} from "@/components/workspace/desk/desk-data";
import type { FleetAgentBinding, FleetTemplate } from "@/core/fleet/types";
import type { ScheduledTask } from "@/core/scheduled-tasks/types";

const NOW = Date.parse("2026-09-24T16:00:00Z");

function task(patch: Partial<ScheduledTask>): ScheduledTask {
  return {
    id: "task-1",
    thread_id: null,
    context_mode: "fresh_thread_per_run",
    assistant_id: "chief-of-staff",
    title: "Chief of Staff",
    prompt: "Brief",
    schedule_type: "cron",
    schedule_spec: { cron: "30 8 * * 1-5" },
    timezone: "America/New_York",
    status: "enabled",
    next_run_at: null,
    last_run_at: null,
    last_run_id: null,
    last_thread_id: null,
    last_error: null,
    run_count: 0,
    created_at: "2026-09-20T00:00:00Z",
    updated_at: "2026-09-20T00:00:00Z",
    ...patch,
  };
}

function template(id: string): FleetTemplate {
  return {
    id,
    version: "1",
    name: id,
    description: "",
    model: "openrouter-opus-5.5",
    skills: [],
    tool_groups: [],
    mcp_plugins: [],
    schedule: { cron: "0 9 * * 1", timezone: "America/New_York" },
    acceptance_criteria: [],
  };
}

describe("desk data", () => {
  it("summarizes a fresh instance as never run and not scheduled", () => {
    expect(summarizeTasks([])).toEqual({
      next: null,
      paused: false,
      last: null,
      lastStatus: "none",
    });
  });

  it("takes the earliest live next run and the latest run's outcome", () => {
    const soon = task({ id: "a", next_run_at: "2026-09-25T12:30:00Z" });
    const paused = task({
      id: "b",
      status: "paused",
      next_run_at: "2026-09-24T17:00:00Z",
    });
    const failedLast = task({
      id: "c",
      next_run_at: "2026-09-28T12:30:00Z",
      last_run_at: "2026-09-24T12:30:00Z",
      last_error: "provider timeout",
    });
    const older = task({ id: "d", last_run_at: "2026-09-23T12:30:00Z" });
    const summary = summarizeTasks([soon, paused, failedLast, older]);
    expect(summary.next?.id).toBe("a");
    expect(summary.last?.id).toBe("c");
    expect(summary.lastStatus).toBe("failed");
    expect(summarizeTasks([paused]).paused).toBe(true);
    expect(summarizeTasks([task({ status: "running" })]).lastStatus).toBe(
      "running",
    );
  });

  it("lists only the last 24 hours of finished work, newest first", () => {
    const fresh = task({
      id: "fresh",
      last_run_at: "2026-09-24T12:30:00Z",
      last_thread_id: "t1",
    });
    const newer = task({
      id: "newer",
      last_run_at: "2026-09-24T15:00:00Z",
      last_thread_id: "t2",
    });
    const stale = task({
      id: "stale",
      last_run_at: "2026-09-23T12:00:00Z",
      last_thread_id: "t3",
    });
    const running = task({
      id: "running",
      status: "running",
      last_run_at: "2026-09-24T15:30:00Z",
      last_thread_id: "t4",
    });
    expect(
      recentOutputs([fresh, stale, running, newer], NOW).map((t) => t.id),
    ).toEqual(["newer", "fresh"]);
  });

  it("matches owner agents and client-stamped copies to their template", () => {
    const tasks = [
      task({ id: "owner", assistant_id: "client-reporter" }),
      task({ id: "stamped", assistant_id: "acme-client-reporter" }),
      task({ id: "other", assistant_id: "revenue-ops" }),
    ];
    expect(tasksOfTemplate("client-reporter", tasks).map((t) => t.id)).toEqual([
      "owner",
      "stamped",
    ]);
    const binding = { scheduled_task_id: "other" } as FleetAgentBinding;
    expect(tasksOfBindings([binding], tasks).map((t) => t.id)).toEqual([
      "other",
    ]);
  });

  it("groups the roster by department and keeps unknown templates", () => {
    const groups = groupByDepartment([
      template("brain-curator"),
      template("chief-of-staff"),
      template("custom-thing"),
    ]);
    expect(groups.map((g) => g.department)).toEqual([
      "Command",
      "Knowledge",
      "Other",
    ]);
  });

  it("links a receipt to the agent's thread, or nowhere before a run", () => {
    expect(receiptPath(task({}))).toBeNull();
    expect(receiptPath(task({ last_thread_id: "thread-9" }))).toBe(
      "/workspace/agents/chief-of-staff/chats/thread-9",
    );
    expect(
      receiptPath(task({ assistant_id: "lead_agent", last_thread_id: "t" })),
    ).toBe("/workspace/chats/t");
  });
});
