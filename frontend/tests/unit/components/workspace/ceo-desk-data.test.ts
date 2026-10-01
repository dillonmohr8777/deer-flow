import { describe, expect, it } from "@rstest/core";

import {
  draftClientLabel,
  formatSeatBurn,
  formatStamp,
  formatTokenCount,
  seatKpiLabel,
  seatStatusLabel,
  seatStatusTone,
} from "@/components/workspace/ceo-desk/ceo-desk-data";
import type { SeatRosterEntry } from "@/core/ceo-desk";

function seat(overrides: Partial<SeatRosterEntry> = {}): SeatRosterEntry {
  return {
    seat_id: "seat-1",
    seat: "CEO",
    agent_name: "lead-agent",
    kpi: "Ship the week's plan",
    status: "claimed",
    weekly_token_budget: 10_000,
    burn_this_week: 3_200,
    paused: false,
    ...overrides,
  };
}

describe("formatStamp", () => {
  it("shows a bare time for today and a date otherwise", () => {
    const now = new Date("2026-09-30T18:00:00Z");
    const today = new Date("2026-09-30T08:05:00Z").toISOString();
    expect(formatStamp(today, now)).not.toBe("");
    expect(formatStamp(today, now)).not.toMatch(/Sep/);
    const yesterday = new Date("2026-09-29T08:05:00Z").toISOString();
    expect(formatStamp(yesterday, now)).toMatch(/Sep/);
  });

  it("returns an empty string for an unparseable date", () => {
    expect(formatStamp("not-a-date")).toBe("");
  });
});

describe("draftClientLabel", () => {
  it("names an internal thread when there is no client", () => {
    expect(draftClientLabel(null)).toBe("Internal");
  });

  it("passes a real client id through", () => {
    expect(draftClientLabel("client-42")).toBe("client-42");
  });
});

describe("formatTokenCount", () => {
  it("shows the plain integer under 1,000", () => {
    expect(formatTokenCount(0)).toBe("0");
    expect(formatTokenCount(512)).toBe("512");
  });

  it("abbreviates thousands to one decimal", () => {
    expect(formatTokenCount(3200)).toBe("3.2K");
    expect(formatTokenCount(10_000)).toBe("10.0K");
  });

  it("never reports a negative or non-finite count", () => {
    expect(formatTokenCount(-5)).toBe("0");
    expect(formatTokenCount(Number.NaN)).toBe("0");
  });
});

describe("formatSeatBurn", () => {
  it("reports burn against the budget when one is set", () => {
    expect(formatSeatBurn(seat())).toBe("3.2K / 10.0K tokens");
  });

  it("calls out an unlimited (zero) budget instead of dividing by it", () => {
    expect(formatSeatBurn(seat({ weekly_token_budget: 0 }))).toBe(
      "3.2K tokens (no budget)",
    );
  });
});

describe("seatKpiLabel", () => {
  it("passes a real KPI through", () => {
    expect(seatKpiLabel(seat({ kpi: "Pipeline created" }))).toBe(
      "Pipeline created",
    );
  });

  it("never renders an em dash for a missing KPI (DESIGN.md)", () => {
    expect(seatKpiLabel(seat({ kpi: "" }))).toBe("Not recorded");
    expect(seatKpiLabel(seat({ kpi: "   " }))).toBe("Not recorded");
  });
});

describe("seat status", () => {
  it("names each status in plain words", () => {
    expect(seatStatusLabel(seat({ status: "claimed" }))).toBe("Claimed");
    expect(seatStatusLabel(seat({ status: "ratified" }))).toBe("Ratified");
    expect(seatStatusLabel(seat({ status: "reopened" }))).toBe("Reopened");
  });

  it("calls out a paused seat regardless of its claim status", () => {
    expect(seatStatusLabel(seat({ status: "ratified", paused: true }))).toBe(
      "Ratified, paused",
    );
  });

  it("tones a paused seat as danger even when ratified", () => {
    expect(seatStatusTone(seat({ status: "ratified", paused: true }))).toBe(
      "danger",
    );
    expect(seatStatusTone(seat({ status: "ratified" }))).toBe("ok");
    expect(seatStatusTone(seat({ status: "claimed" }))).toBe("attention");
    expect(seatStatusTone(seat({ status: "reopened" }))).toBe("idle");
  });
});
