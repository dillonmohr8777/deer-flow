import { expect, test } from "@rstest/core";

import {
  ACCENTS,
  asOfLabel,
  circleLayout,
  easeOutValue,
  oldestPending,
  spendRows,
} from "@/components/workspace/command-center/live-board-model";

const RAINBOW = [
  "#EB5F57",
  "#F58B57",
  "#FAC35F",
  "#91C882",
  "#82AADC",
  "#9B82C8",
  "#C882B4",
];

test("every accent is an ultracode color and tiles never share one", () => {
  const values = Object.values(ACCENTS);
  for (const hex of values) expect(RAINBOW).toContain(hex);
  expect(new Set(values).size).toBe(values.length);
});

test("spend rows keep a missing cap as null, never 0", () => {
  const rows = spendRows({
    enabled: true,
    routes: {
      bulk: {
        model: "m",
        today_usd: 0.5,
        month_usd: 1.5,
        daily_cap_usd: 1,
        monthly_cap_usd: null,
        priced: true,
        unpriced_usage: false,
      },
    },
  });
  expect(rows).toHaveLength(1);
  expect(rows[0]!.today).toEqual({ used: 0.5, cap: 1, ratio: 0.5 });
  expect(rows[0]!.month).toEqual({ used: 1.5, cap: null, ratio: null });
});

test("spend ratio clamps at 1 but keeps the real used amount", () => {
  const [row] = spendRows({
    enabled: true,
    routes: {
      r: {
        model: "m",
        today_usd: 3,
        month_usd: 0,
        daily_cap_usd: 2,
        monthly_cap_usd: 0,
        priced: true,
        unpriced_usage: true,
      },
    },
  });
  expect(row!.today).toEqual({ used: 3, cap: 2, ratio: 1 });
  expect(row!.month.ratio).toBeNull();
  expect(row!.unpriced).toBe(true);
});

test("oldest pending approval is the earliest created_at", () => {
  expect(oldestPending([])).toEqual({ count: 0, oldest: null });
  const out = oldestPending([
    { id: "b", title: "B", created_at: "2026-10-06T10:00:00Z" },
    { id: "a", title: "A", created_at: "2026-10-05T10:00:00Z" },
    { id: "c", title: "C", created_at: "not a date" },
  ]);
  expect(out.count).toBe(3);
  expect(out.oldest?.id).toBe("a");
});

test("circle layout is deterministic and keeps every node inside the box", () => {
  const nodes = [{ id: "a" }, { id: "b" }, { id: "c" }];
  const one = circleLayout(nodes);
  expect(circleLayout(nodes)).toEqual(one);
  for (const n of one) {
    expect(n.x).toBeGreaterThan(0);
    expect(n.x).toBeLessThan(100);
    expect(n.y).toBeGreaterThan(0);
    expect(n.y).toBeLessThan(100);
  }
  expect(circleLayout([{ id: "solo" }])).toHaveLength(1);
});

test("ease-out reaches the target exactly and never overshoots", () => {
  expect(easeOutValue(0, 10, 0)).toBe(0);
  expect(easeOutValue(0, 10, 1)).toBe(10);
  expect(easeOutValue(0, 10, 2)).toBe(10);
  const mid = easeOutValue(0, 10, 0.5);
  expect(mid).toBeGreaterThan(5);
  expect(mid).toBeLessThan(10);
});

test("as-of label says unknown instead of inventing a time", () => {
  expect(asOfLabel(null)).toBe("unknown");
  expect(asOfLabel("garbage")).toBe("unknown");
  expect(asOfLabel("2026-10-06T14:05:00Z", "UTC")).toContain("2:05");
});
