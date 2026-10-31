import { describe, expect, it } from "@rstest/core";

import {
  PLACEHOLDER_STAFF,
  parseStaff,
} from "@/components/momentum/daily/staff-box";

describe("staff roster", () => {
  it("shows role placeholders when nothing is configured", () => {
    expect(parseStaff(undefined)).toBe(PLACEHOLDER_STAFF);
    expect(parseStaff("")).toBe(PLACEHOLDER_STAFF);
    expect(PLACEHOLDER_STAFF.every((person) => person.title === "")).toBe(true);
  });

  it("reads the configured roster, defaulting a missing title", () => {
    const raw = JSON.stringify([
      { slug: "pat-example", name: " Pat Example ", title: "Designer" },
      { slug: "sam-example", name: "Sam Example" },
    ]);

    expect(parseStaff(raw)).toEqual([
      { slug: "pat-example", name: "Pat Example", title: "Designer" },
      { slug: "sam-example", name: "Sam Example", title: "" },
    ]);
  });

  it("falls back to the placeholders on anything malformed", () => {
    for (const raw of [
      "not json",
      "{}",
      "[]",
      JSON.stringify([{ slug: "../escape", name: "Pat Example" }]),
      JSON.stringify([{ slug: "pat-example", name: "" }]),
      JSON.stringify([{ slug: "pat-example", name: "Pat", title: 4 }]),
      JSON.stringify([null]),
    ]) {
      expect(parseStaff(raw)).toBe(PLACEHOLDER_STAFF);
    }
  });
});
