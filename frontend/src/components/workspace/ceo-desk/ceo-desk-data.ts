import type { StatusTone } from "@/components/workspace/page-body";
import type { SeatRosterEntry, SeatStatus } from "@/core/ceo-desk";

/** Short, locale-aware time; empty for a bad date. Mirrors team-data.ts. */
export function formatStamp(iso: string, now: Date = new Date()): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const sameDay = date.toDateString() === now.toDateString();
  return sameDay
    ? date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
    : date.toLocaleDateString([], { month: "short", day: "numeric" });
}

/** A board draft's client, or "Internal" for a thread with no client. */
export function draftClientLabel(clientId: string | null): string {
  return clientId ?? "Internal";
}

/** "48.2K" for large counts, the plain integer below 1,000. */
export function formatTokenCount(tokens: number): string {
  if (!Number.isFinite(tokens) || tokens < 0) return "0";
  if (tokens < 1000) return String(Math.round(tokens));
  return `${(tokens / 1000).toFixed(1)}K`;
}

/** "3.2K / 10K tokens" or "3.2K tokens (no budget)" when unlimited (0). */
export function formatSeatBurn(seat: SeatRosterEntry): string {
  const burn = formatTokenCount(seat.burn_this_week);
  if (seat.weekly_token_budget <= 0) {
    return `${burn} tokens (no budget)`;
  }
  return `${burn} / ${formatTokenCount(seat.weekly_token_budget)} tokens`;
}

const SEAT_STATUS_TONE: Record<SeatStatus, StatusTone> = {
  claimed: "attention",
  ratified: "ok",
  reopened: "idle",
};

/** A paused seat always reads as danger, regardless of its claim status. */
export function seatStatusTone(seat: SeatRosterEntry): StatusTone {
  if (seat.paused) return "danger";
  return SEAT_STATUS_TONE[seat.status];
}

const SEAT_STATUS_LABEL: Record<SeatStatus, string> = {
  claimed: "Claimed",
  ratified: "Ratified",
  reopened: "Reopened",
};

export function seatStatusLabel(seat: SeatRosterEntry): string {
  const base = SEAT_STATUS_LABEL[seat.status];
  return seat.paused ? `${base}, paused` : base;
}
