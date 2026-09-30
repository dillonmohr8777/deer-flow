import { describe, expect, it } from "@rstest/core";

import { formatScheduleTime } from "@/core/utils/datetime";

// Thursday, Sep 24 2026, 3 PM local.
const now = new Date(2026, 8, 24, 15, 0);
const en = (d: Date) => formatScheduleTime(d, "en-US", now);

describe("formatScheduleTime", () => {
  it("names today, tomorrow and yesterday by calendar day", () => {
    expect(en(new Date(2026, 8, 24, 23, 30))).toBe("Today, 11:30 PM");
    // Ten hours away but after midnight: tomorrow, not "today".
    expect(en(new Date(2026, 8, 25, 0, 50))).toBe("Tomorrow, 12:50 AM");
    expect(en(new Date(2026, 8, 25, 8, 50))).toBe("Tomorrow, 8:50 AM");
    expect(en(new Date(2026, 8, 23, 9, 0))).toBe("Yesterday, 9:00 AM");
  });

  it("uses the weekday inside the week, the day beyond it", () => {
    expect(en(new Date(2026, 8, 27, 14, 0))).toBe("Sun, 2:00 PM");
    expect(en(new Date(2026, 8, 18, 8, 50))).toBe("Fri, 8:50 AM");
    expect(en(new Date(2026, 9, 1, 8, 50))).toBe("Oct 1, 8:50 AM");
    expect(en(new Date(2026, 10, 9, 10, 0))).toBe("Nov 9, 10:00 AM");
  });

  it("adds the year only when it differs", () => {
    expect(en(new Date(2027, 0, 4, 9, 0))).toBe("Jan 4, 2027, 9:00 AM");
  });

  it("speaks zh-CN", () => {
    expect(
      formatScheduleTime(new Date(2026, 8, 25, 8, 50), "zh-CN", now),
    ).toMatch(/^明天 /);
  });

  it("returns null for missing or invalid timestamps", () => {
    expect(formatScheduleTime(null, "en-US", now)).toBeNull();
    expect(formatScheduleTime(undefined, "en-US", now)).toBeNull();
    expect(formatScheduleTime("", "en-US", now)).toBeNull();
    expect(formatScheduleTime("not a date", "en-US", now)).toBeNull();
  });
});
