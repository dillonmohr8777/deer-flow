import { describe, expect, it } from "@rstest/core";

import {
  dayGroupKey,
  dayGroupOf,
  dayGroupStartingAt,
} from "@/core/threads/day-groups";
import type { AgentThread } from "@/core/threads/types";

// Tuesday 2026-09-29, 9:30 in the morning local time.
const now = new Date(2026, 8, 29, 9, 30);
const at = (y: number, m: number, d: number, h = 12) =>
  new Date(y, m, d, h).toISOString();

function thread(id: string, updatedAt: string, pinned = false): AgentThread {
  return {
    thread_id: id,
    updated_at: updatedAt,
    metadata: pinned ? { deerflow_pinned: true } : {},
  } as unknown as AgentThread;
}

describe("dayGroupOf", () => {
  it("files by calendar day, not by 24 hour windows", () => {
    expect(dayGroupOf(at(2026, 8, 29, 0), now).kind).toBe("today");
    // Late last night is under 24h ago but still yesterday.
    expect(dayGroupOf(at(2026, 8, 28, 23), now).kind).toBe("yesterday");
    expect(dayGroupOf(at(2026, 8, 27, 1), now).kind).toBe("lastWeek");
    expect(dayGroupOf(at(2026, 8, 23), now).kind).toBe("lastWeek");
  });

  it("files older chats by month, naming the year only when it differs", () => {
    expect(dayGroupOf(at(2026, 8, 20), now)).toEqual({
      kind: "month",
      year: 2026,
      month: 8,
      sameMonth: true,
      sameYear: true,
    });
    expect(dayGroupOf(at(2026, 7, 20), now)).toMatchObject({
      sameMonth: false,
      sameYear: true,
    });
    expect(dayGroupOf(at(2025, 8, 20), now)).toMatchObject({
      year: 2025,
      sameMonth: false,
      sameYear: false,
    });
  });

  it("treats a future timestamp as today and a missing one as undated", () => {
    expect(dayGroupOf(at(2026, 8, 30), now).kind).toBe("today");
    expect(dayGroupOf("", now).kind).toBe("undated");
    expect(dayGroupOf("not a date", now).kind).toBe("undated");
    expect(dayGroupOf(undefined, now).kind).toBe("undated");
  });
});

describe("dayGroupStartingAt", () => {
  it("labels only the first chat of each group, pinned chats first", () => {
    const threads = [
      thread("p", at(2025, 1, 1), true),
      thread("a", at(2026, 8, 29, 8)),
      thread("b", at(2026, 8, 29, 7)),
      thread("c", at(2026, 8, 28)),
      thread("d", at(2026, 7, 2)),
      thread("e", at(2026, 7, 1)),
    ];
    const labels = threads.map((_, i) => {
      const group = dayGroupStartingAt(threads, i, now);
      return group ? dayGroupKey(group) : null;
    });
    expect(labels).toEqual([
      "pinned",
      "today",
      null,
      "yesterday",
      "month-2026-7",
      null,
    ]);
  });

  it("returns null past the end of the list", () => {
    expect(dayGroupStartingAt([], 0, now)).toBeNull();
  });
});
