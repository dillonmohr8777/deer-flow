import type { StatusTone } from "@/components/workspace/page-body";

/**
 * Words for the codes the OpenAI crew service raises or stores
 * (`backend/app/gateway/openai_agent_service.py` and its router). The page
 * never shows a snake_case code: a known one gets its sentence, an unknown
 * one the generic sentence, and anything already a sentence passes through.
 */
const UNAVAILABLE =
  "The OpenAI crew is not available on this server right now.";
const UNCONFIRMED =
  "OpenAI did not confirm what happened. Refresh to check the session before trying again.";
const BUSY = "The crew is still working. Wait for it to finish, or stop it.";

export const CREW_MESSAGES: Record<string, string> = {
  not_enabled: "The OpenAI crew is turned off on this server.",
  missing_api_key:
    "OpenAI is not connected on this server. An admin adds the API key.",
  sdk_upgrade_required:
    "This server's OpenAI library is out of date. An admin needs to update it.",
  openai_agents_unavailable: UNAVAILABLE,
  unsafe_storage: UNAVAILABLE,
  local_persistence_failed:
    "The session could not be saved on this server. Refresh to check it before trying again.",
  provider_outcome_unknown: UNCONFIRMED,
  deadline_cancel_outcome_unknown:
    "The turn ran out of time and OpenAI did not confirm it stopped.",
  provider_read_failed: "OpenAI could not be read just now. Try again.",
  owner_admission_limit:
    "You have as many sessions running as you can. Wait for one to finish.",
  active_session_limit:
    "You have as many sessions running as you can. Wait for one to finish.",
  session_admission_limit: BUSY,
  session_busy: BUSY,
  operation_pending:
    "The last action is not confirmed yet. A new task waits until it is.",
  idempotency_conflict:
    "That request was already sent with a different task. Start a new session.",
  not_found: "This session no longer exists.",
  artifact_size_unavailable_or_exceeded: "The file is too large to download.",
  artifact_read_failed: "The file could not be read from OpenAI. Try again.",
  workspace_scope_changed:
    "The workspace changed. Refresh to read its sessions.",
  hosted_browser_disabled_pending_action_policy:
    "Browser actions are not available in this release.",
};

export const CREW_GENERIC = "The OpenAI crew could not complete that.";

/** A raised or stored code, or an Error carrying one, in words. */
export function crewWords(value: unknown): string {
  const text =
    value instanceof Error
      ? value.message
      : typeof value === "string"
        ? value
        : "";
  const code = text.trim();
  if (!code) return CREW_GENERIC;
  if (CREW_MESSAGES[code]) return CREW_MESSAGES[code];
  if (/^[a-z][a-z0-9_]*$/.test(code)) return CREW_GENERIC;
  if (code === "OpenAI agent request failed") return CREW_GENERIC;
  return code;
}

/**
 * A session's or turn's state in the board's words: only running work is
 * Working, waiting is Queued, and an outcome nobody confirmed is Unconfirmed.
 */
export function crewState(status: string): {
  label: string;
  tone: StatusTone;
} {
  switch (status) {
    case "in_progress":
    case "running":
      return { label: "Working", tone: "active" };
    case "creating":
    case "queued":
      return { label: "Queued", tone: "idle" };
    case "cancelling":
      return { label: "Stopping", tone: "idle" };
    case "requires_action":
      return { label: "Needs an action", tone: "attention" };
    case "completed":
      return { label: "Done", tone: "ok" };
    case "failed":
      return { label: "Failed", tone: "danger" };
    case "cancelled":
      return { label: "Stopped", tone: "idle" };
    case "idle":
      return { label: "Ready", tone: "idle" };
    case "unknown":
      return { label: "Unconfirmed", tone: "attention" };
    default:
      return { label: "Unknown", tone: "unknown" };
  }
}

/** Running work, the only state that earns a pin. */
export function crewWorking(status: string): boolean {
  return status === "in_progress" || status === "running";
}

type Item = {
  type: string;
  role: string | null;
  subagent_id: string | null;
  phase?: string | null;
};

/** Specialists numbered in the order they first appear in a session. */
export function specialistNumbers(
  items: readonly { subagent_id: string | null }[],
): Map<string, number> {
  const numbers = new Map<string, number>();
  for (const item of items)
    if (item.subagent_id && !numbers.has(item.subagent_id))
      numbers.set(item.subagent_id, numbers.size + 1);
  return numbers;
}

/**
 * Who wrote an item, in words. A provider id such as `sa_1` never reaches
 * the page: specialists go by their number.
 */
export function crewAuthor(item: Item, numbers: Map<string, number>): string {
  const n = item.subagent_id ? numbers.get(item.subagent_id) : undefined;
  if (item.type === "create_subagent_call")
    return n ? `MomoBot, to specialist ${n}` : "MomoBot, delegating";
  if (n)
    return item.phase === "final_answer"
      ? `Specialist ${n}, final answer`
      : `Specialist ${n}`;
  if (item.role === "user") return "You";
  return "MomoBot";
}
