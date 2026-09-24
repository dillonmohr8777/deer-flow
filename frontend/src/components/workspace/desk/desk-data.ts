import type { FleetAgentBinding, FleetTemplate } from "@/core/fleet/types";
import type { ScheduledTask } from "@/core/scheduled-tasks/types";
import { pathOfThread } from "@/core/threads/utils";

const DAY_MS = 24 * 60 * 60 * 1000;

/** The private roster's departments, in desk order (GOAL.md, 2026-09-24). */
export const DEPARTMENTS: ReadonlyArray<readonly [string, readonly string[]]> =
  [
    ["Command", ["chief-of-staff", "delivery-auditor"]],
    ["Research", ["research-swarm", "muse-scout", "job-radar"]],
    [
      "Marketing",
      [
        "marketing-lead",
        "seo-geo-strategist",
        "content-studio",
        "paid-media-analyst",
        "outreach-drafter",
      ],
    ],
    ["Engineering", ["eng-lead", "reliability-scout", "qa-critic"]],
    ["Web", ["web-designer", "web-builder"]],
    ["Video", ["video-director", "video-editor"]],
    ["Client desk", ["momo-concierge", "client-reporter"]],
    ["Revenue", ["revenue-ops"]],
    ["Knowledge", ["brain-curator"]],
  ];

export type DepartmentGroup = {
  department: string;
  templates: FleetTemplate[];
};

// ponytail: department lives here, not on the template; move it into
// template.yaml and the fleet API if a second roster ever needs one.
export function groupByDepartment(templates: FleetTemplate[]) {
  const known = new Set<string>(DEPARTMENTS.flatMap(([, ids]) => ids));
  const groups: DepartmentGroup[] = DEPARTMENTS.map(([department, ids]) => ({
    department,
    templates: ids.flatMap((id) => templates.filter((t) => t.id === id)),
  }));
  groups.push({
    department: "Other",
    templates: templates.filter((t) => !known.has(t.id)),
  });
  return groups.filter((group) => group.templates.length > 0);
}

/**
 * Schedules that run a template: the owner's agent named after it, or a
 * client's stamped copy, which clients.py names "<client-slug>-<template-id>".
 */
// ponytail: matched by agent name; add template_id to scheduled tasks if names collide.
export function tasksOfTemplate(templateId: string, tasks: ScheduledTask[]) {
  return tasks.filter(
    (task) =>
      task.assistant_id === templateId ||
      (task.assistant_id?.endsWith(`-${templateId}`) ?? false),
  );
}

/** Schedules bound to one client through its stamped fleet agents. */
export function tasksOfBindings(
  bindings: FleetAgentBinding[],
  tasks: ScheduledTask[],
) {
  const ids = new Set(bindings.map((binding) => binding.scheduled_task_id));
  return tasks.filter((task) => ids.has(task.id));
}

export type LastRunStatus = "running" | "failed" | "completed" | "none";

export type TaskSummary = {
  /** Earliest upcoming run among schedules that are not paused. */
  next: ScheduledTask | null;
  /** Schedules exist, but every one of them is paused. */
  paused: boolean;
  /** The schedule that ran most recently. */
  last: ScheduledTask | null;
  lastStatus: LastRunStatus;
};

const time = (iso: string | null) => (iso ? Date.parse(iso) : NaN);

export function summarizeTasks(tasks: ScheduledTask[]): TaskSummary {
  let next: ScheduledTask | null = null;
  let last: ScheduledTask | null = null;
  for (const task of tasks) {
    if (
      task.status !== "paused" &&
      time(task.next_run_at) < (next ? time(next.next_run_at) : Infinity)
    ) {
      next = task;
    }
    if (time(task.last_run_at) > (last ? time(last.last_run_at) : -Infinity)) {
      last = task;
    }
  }
  const paused =
    tasks.length > 0 && tasks.every((task) => task.status === "paused");
  // complete_run() clears last_error on success and sets it on failure.
  const lastStatus: LastRunStatus = tasks.some((t) => t.status === "running")
    ? "running"
    : !last
      ? "none"
      : last.last_error
        ? "failed"
        : "completed";
  return { next, paused, last, lastStatus };
}

/** Finished scheduled work from the last 24 hours, newest first. */
export function recentOutputs(tasks: ScheduledTask[], now: number) {
  return tasks
    .filter(
      (task) =>
        task.status !== "running" &&
        task.last_thread_id !== null &&
        now - time(task.last_run_at) < DAY_MS,
    )
    .sort((a, b) => time(b.last_run_at) - time(a.last_run_at));
}

/** Where a schedule's latest receipt lives: the thread its last run wrote. */
export function receiptPath(task: ScheduledTask): string | null {
  if (!task.last_thread_id) return null;
  const agent =
    task.assistant_id && task.assistant_id !== "lead_agent"
      ? task.assistant_id
      : undefined;
  return pathOfThread(
    task.last_thread_id,
    agent ? { agent_name: agent } : undefined,
  );
}

function startOfDay(date: Date) {
  return new Date(
    date.getFullYear(),
    date.getMonth(),
    date.getDate(),
  ).getTime();
}

/** "Today 9:00 PM", "Tomorrow 8:30 AM", "Fri 9:00 AM", or "Sep 19". */
export function formatWhen(iso: string, now = new Date()): string {
  const at = new Date(iso);
  const days = Math.round((startOfDay(at) - startOfDay(now)) / DAY_MS);
  const clock = at.toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
  });
  if (days === 0) return `Today ${clock}`;
  if (days === 1) return `Tomorrow ${clock}`;
  if (days === -1) return `Yesterday ${clock}`;
  if (days > 1 && days < 7) {
    return `${at.toLocaleDateString(undefined, { weekday: "short" })} ${clock}`;
  }
  return at.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
