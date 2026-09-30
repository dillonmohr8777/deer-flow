import type { StatusTone } from "@/components/workspace/page-body";
import type { WorkflowRun } from "@/core/workflows/types";

/**
 * Plain words for every code the workflow service stores or returns
 * (`workflow_service.py` keeps only `[a-z0-9_]` codes). Each says what
 * happened and, where there is one, the next step.
 */
const MESSAGES: Record<string, string> = {
  // Admission and requests
  queue_full:
    "The workflow queue is full. Wait for a slot before trying again.",
  daily_model_budget_exhausted:
    "The daily model-call budget has been reached. Try again tomorrow.",
  framework_unavailable: "This execution framework is currently unavailable.",
  not_enabled: "Workflow execution is disabled.",
  input_invalid: "Check the required fields and their allowed bounds.",
  idempotency_conflict:
    "This request was already sent with different inputs. Start a new run instead.",
  invalid_idempotency_key: "The request key was invalid. Start the run again.",
  not_found: "This run or workflow no longer exists. Refresh the page.",
  service_already_running:
    "The workflow service is still starting. Try again in a moment.",
  service_unavailable: "The workflow service is unavailable right now.",
  workflow_runtime_unavailable:
    "The workflow runtime is unavailable right now.",
  native_runtime_unavailable: "The agent runtime is unavailable right now.",
  workflow_revision_changed:
    "This workflow changed since the run started, so it cannot continue. Start a new run.",
  owner_authorization_changed:
    "Your access changed since this run started, so it was stopped. Start a new run if you still have access.",
  workflow_request_failed: "The workflow service did not answer.",
  invalid_workflow_response:
    "The workflow service sent back something this page cannot read.",
  // Run outcomes
  acceptance_failed:
    "The result did not pass its acceptance checks, so it was not accepted.",
  run_model_budget_exhausted:
    "The run used all of its model calls before it finished.",
  run_token_budget_exhausted:
    "The run used all of its token budget before it finished.",
  model_context_too_large:
    "The inputs were too long for the model. Shorten the brief or sources and run it again.",
  provider_token_limit_exceeded:
    "The model hit its output limit before it finished.",
  model_policy_denied: "The model provider declined this request.",
  provider_request_failed: "The model provider did not answer.",
  provider_receipt_invalid:
    "The model provider's receipt could not be verified, so the result was not used.",
  uncertain_provider_attempt:
    "The provider outcome is unconfirmed. This run is held until it can be reconciled.",
  browser_unavailable: "Browser evidence capture is unavailable right now.",
  browser_evidence_unverified:
    "The browser evidence could not be verified, so the result was not accepted.",
  workflow_execution_failed: "The workflow stopped on an unexpected error.",
  cancelled: "This run was cancelled.",
  native_run_cancelled: "This run was cancelled.",
  interrupted_by_shutdown: "The server restarted while this run was working.",
  interrupted_by_restart: "The server restarted while this run was working.",
  native_admission_interrupted:
    "The server restarted before this run was admitted.",
  native_admission_uncertain:
    "It is not confirmed that this run was admitted. Check your runs before trying again.",
  // Resume and cancel
  resume_limit:
    "This run has been resumed as many times as allowed. It cannot be resumed again.",
  run_not_interrupted:
    "This run is no longer interrupted. Refresh its saved state.",
  run_not_running: "This run is no longer running. Refresh its saved state.",
  // Records and artifacts
  artifact_too_large: "The result is too large to save as an artifact.",
  artifact_unavailable: "The saved artifact is unavailable.",
  artifact_readback_failed:
    "The saved artifact did not match its receipt, so it was not handed over.",
  artifact_identity_conflict:
    "A different artifact is already saved for this run.",
  attempt_state_conflict:
    "This run's saved state changed underneath it. Refresh and check the run.",
  call_id_conflict:
    "This run's saved state changed underneath it. Refresh and check the run.",
  invalid_call_id: "This run's saved state could not be read.",
  event_too_large: "A step reported more than the run can record.",
  unsafe_state_path: "The workflow service refused an unsafe storage path.",
  session_closed: "The browser session closed before capture finished.",
  workflow_native_namespace_migration_required:
    "Workflow storage needs an upgrade before runs can start.",
};

export function explanation(error: Error): string {
  const known = MESSAGES[error.message];
  if (known) return known;
  // A bare snake_case code is an internal identifier, not a reason a person
  // can act on (DESIGN.md Copy); a sentence from the server passes through.
  return /^[a-z0-9_]+$/.test(error.message)
    ? "The workflow service could not complete this request."
    : error.message;
}

/** A run's status as a word beside a shape; colour is never the only signal. */
export function runState(run: WorkflowRun): {
  tone: StatusTone;
  label: string;
} {
  switch (run.status) {
    case "running":
      return { tone: "active", label: "Running" };
    case "queued":
      return { tone: "idle", label: "Queued" };
    case "interrupted":
      return { tone: "idle", label: "Interrupted" };
    case "completed":
      return run.accepted
        ? { tone: "ok", label: "Accepted" }
        : { tone: "attention", label: "Not accepted" };
    case "failed":
      return { tone: "danger", label: "Failed" };
    case "cancelled":
      return { tone: "idle", label: "Cancelled" };
    default:
      return { tone: "unknown", label: "Unknown state" };
  }
}

/** "Today, 2:05 PM" for today, "Sep 28, 2:05 PM" otherwise. */
export function runTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "Time not recorded";
  const clock = date.toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
  });
  if (date.toDateString() === new Date().toDateString())
    return `Today, ${clock}`;
  const sameYear = date.getFullYear() === new Date().getFullYear();
  return `${date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    ...(sameYear ? {} : { year: "numeric" }),
  })}, ${clock}`;
}

/** Plain names for the steps `deerflow.workflows.engine` journals. */
const STEP_NAMES: Record<string, string> = {
  validate: "Check the inputs",
  research: "Gather public sources",
  stagehand: "Capture browser evidence",
  plan: "Plan the work",
  draft: "Draft the result",
  revise: "Revise after review",
  verify: "Independent review",
  accept: "Acceptance checks",
};

/** The engine's step detail codes; a sentence from a worker passes through. */
const STEP_DETAILS: Record<string, string> = {
  input_schema_validated: "Every field is present and inside its limits.",
  not_required: "Not needed for this workflow.",
  public_read_only_sources: "Reading public pages only.",
  sources_retrieved: "Sources read and recorded as evidence.",
  schema_and_independent_review_passed:
    "The result matched its format and passed the independent review.",
};

const EVIDENCE_KINDS: Record<string, string> = {
  input: "Supplied input",
  browserbase: "Browser capture",
  review: "Review receipt",
};

/** "not_required" or "Review" to "Not required" or "Review". */
export function humanize(code: string): string {
  const words = code.replaceAll("_", " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export type RunStep = WorkflowRun["steps"][number];

/**
 * The journal logs a step once as it starts and again as it ends, so the
 * receipt shows each step once, in the order it began, at its latest word.
 */
export function stepsOnce(steps: RunStep[]): RunStep[] {
  const latest = new Map<string, RunStep>();
  for (const step of steps) latest.set(step.name, step);
  return [...latest.values()];
}

export function stepName(name: string): string {
  return STEP_NAMES[name] ?? humanize(name);
}

/** A detail code in words; an unknown bare code is an internal id, so none. */
export function stepDetail(detail?: string): string | null {
  if (!detail) return null;
  return STEP_DETAILS[detail] ?? (/^[a-z0-9_]+$/.test(detail) ? null : detail);
}

/**
 * A step's word beside its shape. A step still "running" in a run that has
 * ended is where the run stopped, not work in progress.
 */
export function stepState(
  step: RunStep,
  run: WorkflowRun,
): { tone: StatusTone; label: string } {
  switch (step.status) {
    case "completed":
      return { tone: "ok", label: "Done" };
    case "failed":
      return { tone: "danger", label: "Failed" };
    case "running":
      if (run.status === "running") return { tone: "active", label: "Working" };
      return run.status === "failed"
        ? { tone: "danger", label: "Stopped here" }
        : { tone: "idle", label: "Stopped here" };
    default:
      return { tone: "unknown", label: humanize(step.status) };
  }
}

export function evidenceKind(kind: string): string {
  return EVIDENCE_KINDS[kind] ?? humanize(kind);
}

/** 48213 to "47.1 KB". */
export function byteSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} bytes`;
  const kb = bytes / 1024;
  return kb < 1024 ? `${kb.toFixed(1)} KB` : `${(kb / 1024).toFixed(1)} MB`;
}
