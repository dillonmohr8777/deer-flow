import { z } from "zod";

import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

const recordId = z
  .string()
  .refine(
    (value) => [...value].length >= 1 && [...value].length <= 64,
    "Participant and request IDs must contain 1 to 64 characters.",
  );
const awareDate = z
  .string()
  .datetime({ offset: true, message: "Choose a valid date with a time zone." });
const boundedText = (label: string, max: number) =>
  z
    .string()
    .refine(
      (value) => value.trim().length > 0 && [...value].length <= max,
      `${label} must contain 1 to ${max} characters and cannot be blank.`,
    );
const planSchema = z
  .object({
    outcome: boundedText("Outcome", 2000),
    assignee_user_id: recordId.nullable(),
    due_at: awareDate.nullable(),
    dependency_thread_ids: z
      .array(recordId)
      .max(10, "Choose at most 10 dependencies."),
    verifier_user_id: recordId.nullable(),
    status: z.enum(["planned", "in_progress", "blocked", "reported_complete"]),
    next_action: boundedText("Next action", 2000),
    evidence_refs: z
      .array(
        z
          .object({
            kind: z.enum(["source", "delivery"]),
            reference: boundedText("Evidence reference", 512),
          })
          .strict(),
      )
      .max(10, "Record at most 10 evidence references."),
  })
  .strict()
  .superRefine((plan, context) => {
    if (
      new Set(plan.dependency_thread_ids).size !==
      plan.dependency_thread_ids.length
    ) {
      context.addIssue({
        code: "custom",
        message: "Dependency requests must be unique.",
      });
    }
    if (
      plan.status === "reported_complete" &&
      plan.evidence_refs.length === 0
    ) {
      context.addIssue({
        code: "custom",
        message: "Reported completion requires an evidence reference.",
      });
    }
    if (new TextEncoder().encode(JSON.stringify(plan)).length > 8000) {
      context.addIssue({
        code: "custom",
        message:
          "The work plan must fit within 8000 bytes. Shorten its text or references.",
      });
    }
  });

export type WorkPlan = z.infer<typeof planSchema>;

const recordSchema = z
  .object({
    schema: z.literal("internal_work_plan.v1"),
    revision: z.number().int().min(0).max(2147483647),
    plan: planSchema.nullable(),
    recorded_by_user_id: recordId.nullable(),
    recorded_at: awareDate.nullable(),
    verification: z.literal("staff_recorded_unverified"),
    source: z
      .object({ table: z.literal("board_portal"), id: recordId })
      .strict(),
  })
  .strict();

export type WorkPlanRecord = z.infer<typeof recordSchema>;

type Scope = { workspace: string; requestId: string; signal?: AbortSignal };

const participantSchema = z
  .object({
    user_id: recordId,
    email: boundedText("Account email", 320),
    role: z.enum(["owner", "admin", "account_manager"]),
  })
  .strict();
const participantsSchema = z
  .object({
    schema: z.literal("work_plan_participants.v1"),
    source: z.object({ thread_id: recordId }).strict(),
    items: z.array(participantSchema).max(100),
    selected_items: z.array(participantSchema).max(2),
    limit: z.number().int().min(1).max(100),
    has_more: z.boolean(),
    next_cursor: z.string().min(1).max(512).nullable(),
  })
  .strict()
  .superRefine((page, context) => {
    if (
      page.items.length > page.limit ||
      new Set(page.items.map((item) => item.user_id)).size !==
        page.items.length ||
      new Set(page.selected_items.map((item) => item.user_id)).size !==
        page.selected_items.length ||
      page.has_more !== (page.next_cursor !== null) ||
      (page.has_more && page.items.length === 0) ||
      page.selected_items.some((selected) =>
        page.items.some(
          (item) =>
            item.user_id === selected.user_id &&
            (item.email !== selected.email || item.role !== selected.role),
        ),
      )
    ) {
      context.addIssue({
        code: "custom",
        message: "Invalid participant page.",
      });
    }
  });

export type WorkPlanParticipant = z.infer<typeof participantSchema>;
export type WorkPlanParticipants = z.infer<typeof participantsSchema>;

export async function getWorkPlanParticipants({
  workspace,
  requestId,
  signal,
  cursor = null,
  limit = 50,
}: Scope & {
  cursor?: string | null;
  limit?: number;
}): Promise<WorkPlanParticipants> {
  if (
    !Number.isInteger(limit) ||
    limit < 1 ||
    limit > 100 ||
    (cursor !== null && (cursor.length === 0 || cursor.length > 512))
  ) {
    throw new Error("Invalid teammate page request.");
  }
  const search = new URLSearchParams({ limit: String(limit) });
  if (cursor !== null) search.set("cursor", cursor);
  const response = await fetch(
    `${getBackendBaseURL()}/api/client-portal/threads/${encodeURIComponent(requestId)}/work-plan/participants?${search}`,
    {
      method: "GET",
      headers: { "X-Portal-Workspace": workspace },
      cache: "no-store",
      signal,
    },
  );
  const body: unknown = await response.json().catch(() => null);
  signal?.throwIfAborted();
  if (!response.ok) {
    throw new Error(`Could not load eligible teammates (${response.status}).`);
  }
  const parsed = participantsSchema.safeParse(body);
  if (
    !parsed.success ||
    parsed.data.source.thread_id !== requestId ||
    parsed.data.limit !== limit ||
    (cursor !== null && parsed.data.next_cursor === cursor)
  ) {
    throw new Error("The server returned an invalid teammate directory.");
  }
  return parsed.data;
}

export function validateWorkPlan(plan: WorkPlan, requestId: string): void {
  const parsed = planSchema.safeParse(plan);
  if (!parsed.success)
    throw new Error(
      parsed.error.issues[0]?.message ?? "Check the work plan fields.",
    );
  if (parsed.data.dependency_thread_ids.includes(requestId)) {
    throw new Error("A request cannot depend on itself.");
  }
}

async function readResponse(
  response: Response,
  requestId: string,
  action: "load" | "save",
): Promise<WorkPlanRecord> {
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const detail =
      body && typeof body === "object" && "detail" in body ? body.detail : null;
    throw new Error(
      typeof detail === "string"
        ? detail
        : `Could not ${action} the work plan (${response.status}). ${response.status === 422 ? "Check the work plan fields." : "Try again or reload the recorded plan."}`,
    );
  }
  const parsed = recordSchema.safeParse(body);
  if (!parsed.success || parsed.data.source.id !== requestId) {
    throw new Error(
      "The server returned an invalid work plan. Reload before continuing.",
    );
  }
  if (parsed.data.plan) validateWorkPlan(parsed.data.plan, requestId);
  return parsed.data;
}

export async function getWorkPlan({
  workspace,
  requestId,
  signal,
}: Scope): Promise<WorkPlanRecord> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/client-portal/threads/${encodeURIComponent(requestId)}/work-plan`,
    {
      method: "GET",
      headers: { "X-Portal-Workspace": workspace },
      cache: "no-store",
      signal,
    },
  );
  return readResponse(response, requestId, "load");
}

export async function putWorkPlan({
  workspace,
  requestId,
  expectedRevision,
  plan,
  signal,
}: Scope & {
  expectedRevision: number;
  plan: WorkPlan;
}): Promise<WorkPlanRecord> {
  if (
    !Number.isInteger(expectedRevision) ||
    expectedRevision < 0 ||
    expectedRevision > 2147483646
  ) {
    throw new Error("Reload the recorded plan before saving its revision.");
  }
  validateWorkPlan(plan, requestId);
  const response = await fetch(
    `${getBackendBaseURL()}/api/client-portal/threads/${encodeURIComponent(requestId)}/work-plan`,
    {
      method: "PUT",
      headers: {
        "X-Portal-Workspace": workspace,
        "Content-Type": "application/json",
      },
      cache: "no-store",
      signal,
      body: JSON.stringify({ expected_revision: expectedRevision, plan }),
    },
  );
  const saved = await readResponse(response, requestId, "save");
  if (!saved.plan || saved.revision !== expectedRevision + 1) {
    throw new Error(
      "The server did not confirm the saved work plan. Reload before continuing.",
    );
  }
  return saved;
}
