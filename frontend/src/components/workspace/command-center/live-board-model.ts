import type { SpendReport } from "@/core/command-center";

/** The ultracode rainbow, one per tile. Accents are borders and dots only: text stays in the page ink. */
export const ACCENTS = {
  spend: "#EB5F57",
  approvals: "#F58B57",
  evals: "#FAC35F",
  agents: "#91C882",
  lobby: "#82AADC",
  ledger: "#9B82C8",
  header: "#C882B4",
} as const;

type Meter = { used: number; cap: number | null; ratio: number | null };

function meter(used: number, cap: number | null): Meter {
  // A cap of 0 or null cannot make a ratio, and a missing cap is not "unlimited".
  const ratio = cap && cap > 0 ? Math.min(used / cap, 1) : null;
  return { used, cap, ratio };
}

export function spendRows(report: SpendReport) {
  return Object.entries(report.routes).map(([name, r]) => ({
    name,
    model: r.model,
    today: meter(r.today_usd, r.daily_cap_usd),
    month: meter(r.month_usd, r.monthly_cap_usd),
    unpriced: r.unpriced_usage || !r.priced,
  }));
}

export function oldestPending(
  items: { id: string; title: string; created_at: string }[],
) {
  let oldest: (typeof items)[number] | null = null;
  let oldestMs = Infinity;
  for (const item of items) {
    const ms = Date.parse(item.created_at);
    if (!Number.isNaN(ms) && ms < oldestMs) {
      oldest = item;
      oldestMs = ms;
    }
  }
  return { count: items.length, oldest };
}

/** Even spread on a circle inside a 0..100 box, with room for labels. */
export function circleLayout(nodes: { id: string }[]) {
  const r = 30;
  return nodes.map((n, i) => {
    const angle = (2 * Math.PI * i) / nodes.length - Math.PI / 2;
    return {
      id: n.id,
      x: 50 + r * Math.cos(angle),
      y: 50 + r * Math.sin(angle),
    };
  });
}

/** Cubic ease-out from `from` to `to` over t in 0..1. */
export function easeOutValue(from: number, to: number, t: number) {
  const p = Math.min(Math.max(t, 0), 1);
  return from + (to - from) * (1 - Math.pow(1 - p, 3));
}

export function asOfLabel(
  value: string | number | null | undefined,
  timeZone?: string,
) {
  if (value === null || value === undefined || value === "") return "unknown";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "unknown";
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZone,
  }).format(d);
}

export function waitingFor(createdAt: string, now = Date.now()) {
  const ms = now - Date.parse(createdAt);
  if (Number.isNaN(ms) || ms < 0) return "unknown";
  const h = Math.floor(ms / 3_600_000);
  if (h >= 48) return `${Math.floor(h / 24)} days`;
  if (h >= 1) return `${h} h`;
  return `${Math.max(1, Math.floor(ms / 60_000))} min`;
}
