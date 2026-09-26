import type { StatusTone } from "@/components/workspace/page-body";
import type {
  BoardMessage,
  BoardThread,
  BoardThreadKind,
  BoardThreadStatus,
} from "@/core/board";

/** Mirrors ``deerflow.board.workflow``'s ``new``/``triaged`` -> ... chain. */
export const STATUS_LABEL: Record<BoardThreadStatus, string> = {
  new: "New",
  triaged: "Triaged",
  drafted: "Drafted",
  approved: "Approved",
  replied: "Replied",
  closed: "Closed",
};

export const KIND_LABEL: Record<BoardThreadKind, string> = {
  post: "Post",
  ticket: "Ticket",
  concern: "Concern",
  dm: "DM",
};

export const KIND_OPTIONS: ReadonlyArray<{
  value: BoardThreadKind;
  label: string;
}> = [
  { value: "post", label: KIND_LABEL.post },
  { value: "ticket", label: KIND_LABEL.ticket },
  { value: "concern", label: KIND_LABEL.concern },
  { value: "dm", label: KIND_LABEL.dm },
];

export const STATUS_FILTERS: ReadonlyArray<{
  value: BoardThreadStatus | "all";
  label: string;
}> = [
  { value: "all", label: "All" },
  { value: "new", label: STATUS_LABEL.new },
  { value: "triaged", label: STATUS_LABEL.triaged },
  { value: "drafted", label: STATUS_LABEL.drafted },
  { value: "approved", label: STATUS_LABEL.approved },
  { value: "replied", label: STATUS_LABEL.replied },
  { value: "closed", label: STATUS_LABEL.closed },
];

export function statusTone(status: BoardThreadStatus): StatusTone {
  switch (status) {
    case "new":
    case "triaged":
    case "drafted":
      return "attention";
    case "approved":
      return "active";
    case "replied":
      return "ok";
    case "closed":
      return "idle";
  }
}

/** ``assert_can_draft``: Momo may draft only from ``new`` or ``triaged``. */
export function canDraft(status: BoardThreadStatus): boolean {
  return status === "new" || status === "triaged";
}

/** ``assert_can_approve``: only from ``drafted``, and only an owner/admin. */
export function canApprove(status: BoardThreadStatus): boolean {
  return status === "drafted";
}

/** ``assert_can_reply``: only from ``approved``, and only an owner/admin. */
export function canSendReply(status: BoardThreadStatus): boolean {
  return status === "approved";
}

/** Newest-updated thread first. */
export function sortThreadsByUpdated(threads: BoardThread[]): BoardThread[] {
  return [...threads].sort(
    (a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at),
  );
}

/** Momo's most recent drafted reply, to prefill the send-reply editor. */
export function latestMomoDraft(
  messages: BoardMessage[],
): BoardMessage | undefined {
  let latest: BoardMessage | undefined;
  for (const message of messages) {
    if (message.author_kind !== "momo") continue;
    if (
      !latest ||
      Date.parse(message.created_at) > Date.parse(latest.created_at)
    ) {
      latest = message;
    }
  }
  return latest;
}
