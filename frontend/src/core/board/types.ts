export type BoardThreadKind = "post" | "ticket" | "concern" | "dm";

export type BoardThreadStatus =
  | "new"
  | "triaged"
  | "drafted"
  | "approved"
  | "replied"
  | "closed";

export type BoardAuthorKind = "client" | "momo" | "owner";

/** ``deerflow.board.triage.VALID_URGENCIES``. */
export type BoardThreadUrgency = "low" | "normal" | "high" | "urgent";

/** ``BoardThreadResponse`` (``backend/app/gateway/routers/board.py``). */
export type BoardThread = {
  id: string;
  client_id: string | null;
  kind: BoardThreadKind;
  status: BoardThreadStatus;
  subject: string;
  urgency: BoardThreadUrgency | null;
  summary: string | null;
  created_by_user_id: string | null;
  created_at: string;
  updated_at: string;
};

/** ``BoardMessageResponse`` (``backend/app/gateway/routers/board.py``). */
export type BoardMessage = {
  id: string;
  thread_id: string;
  author_kind: BoardAuthorKind;
  author_user_id: string | null;
  body: string;
  created_at: string;
};
