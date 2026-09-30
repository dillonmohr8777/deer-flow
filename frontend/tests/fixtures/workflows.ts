import {
  type WorkflowDefinition,
  type WorkflowRun,
  type WorkflowStatus,
} from "@/core/workflows/types";

/** Synthetic fixtures only: these are not the backend's production catalog. */
export const WORKFLOW_FIXTURES: WorkflowDefinition[] = Array.from(
  { length: 100 },
  (_, index) => ({
    id: `fixture-${String(index + 1).padStart(3, "0")}`,
    title: `Synthetic workflow ${String(index + 1).padStart(3, "0")}`,
    category: index < 50 ? "Marketing" : "Operations",
    summary: "Synthetic task with bounded inputs and a reviewed JSON result.",
    input_schema: {
      type: "object",
      properties: {
        brief: {
          type: "string",
          title: "Task brief",
          minLength: 1,
          maxLength: 1000,
        },
        source_urls: {
          type: "array",
          title: "Source URLs",
          minItems: 1,
          maxItems: 3,
          items: { type: "string" },
        },
        count: { type: "integer", title: "Item count", minimum: 1, maximum: 5 },
        context: {
          type: "object",
          title: "Context JSON",
          properties: { audience: { type: "string", maxLength: 100 } },
          additionalProperties: false,
        },
        include_notes: { type: "boolean", title: "Include notes" },
      },
      required: index % 10 === 9 ? ["brief", "source_urls"] : ["brief"],
      additionalProperties: false,
    },
    output_schema: {
      type: "object",
      properties: { result: { type: "string" } },
      required: ["result"],
      additionalProperties: false,
    },
    steps: ["Plan", "Draft", "Review"],
    acceptance: [
      "Result responds to the supplied brief",
      "Required output fields exist",
    ],
    example_inputs: {
      brief: "Synthetic demo brief: prepare a sample launch checklist.",
      source_urls: ["https://example.com"],
      count: 2,
      context: { audience: "Synthetic audience" },
      include_notes: true,
    },
    requires_browser: index % 10 === 9,
  }),
);
export const WORKFLOW_STATUS: WorkflowStatus = {
  owner_scope: "scope-one",
  enabled: true,
  frameworks: {
    langgraph: { available: true, detail: "Shared native graph" },
    crewai: { available: false, detail: "Isolated worker not configured" },
    mastra: { available: false, detail: "Unavailable" },
    deepagents: { available: false, detail: "Unavailable" },
    agno: { available: false, detail: "Unavailable" },
    agentkit: { available: false, detail: "Unavailable" },
    browser: { available: true, detail: "Guarded public source capture" },
    stagehand: { available: false, detail: "Separate adapter unavailable" },
  },
  limits: {
    max_running: 3,
    max_queued: 100,
    max_model_calls_per_run: 6,
    max_output_tokens_per_run: 8192,
    max_browser_sessions_per_owner: 1,
  },
  running: 0,
  queued: 0,
};
export const WORKFLOW_RUN: WorkflowRun = {
  id: "owned-run",
  workflow_id: "fixture-001",
  title: "Synthetic saved run",
  framework: "langgraph",
  status: "completed",
  accepted: true,
  created_at: "2026-09-30T08:00:00Z",
  updated_at: "2026-09-30T08:00:10Z",
  steps: [
    {
      name: "Review",
      status: "completed",
      worker_id: "worker-scoped-001",
      model: "gpt-6.1-sol",
      effort: "high",
      detail: "Synthetic independent review passed",
    },
  ],
  output: {
    result:
      "<script>window.__workflowScriptRan=true</script> Synthetic verified result",
  },
  evidence: [{ kind: "review", reference: "Synthetic reviewer receipt" }],
  usage: { model_calls: 3, input_tokens: 120, output_tokens: 40, cost: null },
  error: null,
  artifact: null,
};
