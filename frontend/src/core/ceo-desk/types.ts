/** Mirrors ``app.gateway.routers.ceo_desk``'s response models. */

import type { BoardThreadStatus } from "@/core/board";

export type SeatStatus = "claimed" | "ratified" | "reopened";

export interface BoardDraftAwaitingApproval {
  thread_id: string;
  client_id: string | null;
  kind: string;
  subject: string;
  /** Only ``drafted`` (needs Approve) or ``approved`` (needs Send) ever appear here. */
  status: BoardThreadStatus;
  draft_body: string | null;
  updated_at: string;
}

export interface SeatAwaitingRatification {
  seat_id: string;
  seat: string;
  agent_name: string;
  claimed_by_user_id: string | null;
  created_at: string;
}

export interface NeedsMyYes {
  board_drafts: BoardDraftAwaitingApproval[];
  seat_ratifications: SeatAwaitingRatification[];
}

export interface SeatRosterEntry {
  seat_id: string;
  seat: string;
  agent_name: string;
  kpi: string;
  status: SeatStatus;
  weekly_token_budget: number;
  burn_this_week: number;
  paused: boolean;
}

export interface SeatActionResult {
  seat_id: string;
  seat: string;
  agent_name: string;
  status: SeatStatus;
}

export interface DailyDigest {
  digest_text: string;
  shipped_count: number;
  stuck_count: number;
  needs_my_yes_drafts: number;
  needs_my_yes_ratifications: number;
  created_at: string;
}

/** The two Team Board channels the CEO Desk surfaces live. */
export type CeoFeedSlug = "exec" | "fleet";

export interface CeoFeedMessage {
  id: string;
  author_user_id: string;
  /** Resolved server-side: "You", the author's own name, or "Momentum". */
  author_display_name: string;
  body: string;
  created_at: string;
}

export interface CeoFeed {
  channel: CeoFeedSlug;
  /** False only for #fleet before an owner/admin has created it once. */
  exists: boolean;
  messages: CeoFeedMessage[];
}
