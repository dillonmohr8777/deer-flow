import { describe, expect, it } from "@rstest/core";

import { formatCompactStamp } from "@/core/utils/datetime";

const now = new Date(2026, 8, 24, 15, 0);

describe("formatCompactStamp", () => {
  it("shows the time for something from today", () => {
    expect(formatCompactStamp(new Date(2026, 8, 24, 9, 5), "en-US", now)).toBe(
      "9:05 AM",
    );
  });

  it("shows the day for something older this year", () => {
    expect(formatCompactStamp(new Date(2026, 8, 23, 22, 0), "en-US", now)).toBe(
      "Sep 23",
    );
  });

  it("adds the year only when it differs", () => {
    expect(formatCompactStamp(new Date(2025, 11, 30), "en-US", now)).toBe(
      "Dec 30, 2025",
    );
  });

  it("returns null for missing or invalid timestamps", () => {
    expect(formatCompactStamp(null, "en-US", now)).toBeNull();
    expect(formatCompactStamp(undefined, "en-US", now)).toBeNull();
    expect(formatCompactStamp("", "en-US", now)).toBeNull();
    expect(formatCompactStamp("not a date", "en-US", now)).toBeNull();
  });
});
