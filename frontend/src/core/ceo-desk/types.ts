/** Mirrors ``app.gateway.routers.ceo_desk``'s response models. */

export type SeatStatus = "claimed" | "ratified" | "reopened";

export interface BoardDraftAwaitingApproval {
  thread_id: string;
  client_id: string | null;
  kind: string;
  subject: string;
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
