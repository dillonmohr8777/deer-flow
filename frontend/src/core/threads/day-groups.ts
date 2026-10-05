import { isThreadPinned } from "./utils";

/**
 * Where a chat sits in the Chats ledger: pinned chats first, then by the
 * calendar day it was last touched, as a paper ledger is filed.
 */
export type ThreadDayGroup =
  | { kind: "pinned" }
  | { kind: "today" }
  | { kind: "yesterday" }
  | { kind: "lastWeek" }
  // Anything older is filed by month; `sameYear` drops the year from the label.
  | {
      kind: "month";
      year: number;
      month: number;
      sameMonth: boolean;
      sameYear: boolean;
    }
  | { kind: "undated" };

/** Anything filed in a chat ledger: the Chats page and a project's Chats tab. */
export type LedgerThread = {
  metadata?: Record<string, unknown> | null;
  updated_at?: string | null;
};

const DAY_MS = 86_400_000;

function startOfDay(date: Date): number {
  return new Date(
    date.getFullYear(),
    date.getMonth(),
    date.getDate(),
  ).getTime();
}

export function dayGroupOf(
  updatedAt: string | null | undefined,
  now: Date = new Date(),
): ThreadDayGroup {
  if (!updatedAt) return { kind: "undated" };
  const date = new Date(updatedAt);
  if (Number.isNaN(date.getTime())) return { kind: "undated" };
  // Calendar days, not 24h windows, so "Yesterday" means the day before.
  const days = Math.round((startOfDay(now) - startOfDay(date)) / DAY_MS);
  if (days <= 0) return { kind: "today" };
  if (days === 1) return { kind: "yesterday" };
  if (days < 7) return { kind: "lastWeek" };
  const sameYear = date.getFullYear() === now.getFullYear();
  return {
    kind: "month",
    year: date.getFullYear(),
    month: date.getMonth(),
    sameMonth: sameYear && date.getMonth() === now.getMonth(),
    sameYear,
  };
}

export function threadDayGroup(
  thread: LedgerThread,
  now: Date = new Date(),
): ThreadDayGroup {
  return isThreadPinned(thread)
    ? { kind: "pinned" }
    : dayGroupOf(thread.updated_at, now);
}

export function dayGroupKey(group: ThreadDayGroup): string {
  return group.kind === "month"
    ? `month-${group.year}-${group.month}`
    : group.kind;
}

/**
 * The group label to draw before the chat at `index`, or null when it
 * continues the group above it. Adjacent grouping, so a list that is not
 * sorted newest first repeats a label instead of hiding a chat.
 */
export function dayGroupStartingAt(
  threads: readonly LedgerThread[],
  index: number,
  now: Date = new Date(),
): ThreadDayGroup | null {
  const thread = threads[index];
  if (!thread) return null;
  const group = threadDayGroup(thread, now);
  const previous = threads[index - 1];
  if (
    previous &&
    dayGroupKey(threadDayGroup(previous, now)) === dayGroupKey(group)
  ) {
    return null;
  }
  return group;
}

/** The ledger label for a group, in the eyebrow voice the page styles. */
export function dayGroupLabel(
  group: ThreadDayGroup,
  labels: {
    pinned: string;
    today: string;
    yesterday: string;
    lastWeek: string;
    earlierIn: (month: string) => string;
    undated: string;
  },
  locale: string,
): string {
  if (group.kind !== "month") return labels[group.kind];
  const month = new Intl.DateTimeFormat(
    locale === "zh-CN" ? "zh-CN" : "en-US",
    { month: "long", ...(group.sameYear ? {} : { year: "numeric" as const }) },
  ).format(new Date(group.year, group.month, 1));
  return group.sameMonth ? labels.earlierIn(month) : month;
}
