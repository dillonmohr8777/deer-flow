export const FRAMEWORKS = [
  "langgraph",
  "crewai",
  "mastra",
  "deepagents",
  "agno",
  "agentkit",
] as const;
export type WorkflowFramework = (typeof FRAMEWORKS)[number];
export const FRAMEWORK_LABELS: Record<WorkflowFramework, string> = {
  langgraph: "LangGraph",
  crewai: "CrewAI",
  mastra: "Mastra",
  deepagents: "Deep Agents",
  agno: "Agno",
  agentkit: "Inngest AgentKit",
};

export interface InputSchema {
  type?: string | string[];
  title?: string;
  description?: string;
  properties?: Record<string, InputSchema>;
  required?: string[];
  additionalProperties?: boolean | InputSchema;
  items?: InputSchema;
  anyOf?: InputSchema[];
  enum?: unknown[];
  minLength?: number;
  maxLength?: number;
  minItems?: number;
  maxItems?: number;
  minimum?: number;
  maximum?: number;
  format?: string;
}
export interface WorkflowDefinition {
  id: string;
  title: string;
  category: string;
  summary: string;
  input_schema: InputSchema;
  output_schema: InputSchema;
  steps: string[];
  acceptance: string[];
  example_inputs: Record<string, unknown>;
  requires_browser: boolean;
}
export interface WorkflowStatus {
  owner_scope: string;
  enabled: boolean;
  frameworks: Partial<
    Record<
      WorkflowFramework | "stagehand" | "browser",
      { available: boolean; detail: string }
    >
  >;
  limits: {
    max_running: number;
    max_queued: number;
    max_model_calls_per_run: number;
    max_output_tokens_per_run: number;
    max_browser_sessions_per_owner: number;
  };
  running: number;
  queued: number;
}
export interface WorkflowRun {
  id: string;
  workflow_id: string;
  title: string;
  framework: WorkflowFramework;
  status:
    | "queued"
    | "running"
    | "interrupted"
    | "completed"
    | "failed"
    | "cancelled";
  accepted: boolean;
  created_at: string;
  updated_at: string;
  steps: {
    name: string;
    status: string;
    worker_id?: string;
    model?: string;
    effort?: string;
    detail?: string;
  }[];
  output: Record<string, unknown> | null;
  evidence: {
    kind: string;
    reference: string;
    sha256?: string;
    bytes?: number;
  }[];
  usage: {
    model_calls: number;
    input_tokens: number;
    output_tokens: number;
    cost: number | null;
    complete?: boolean;
    unknown_model_calls?: number;
  };
  error: string | null;
  artifact: { sha256: string; bytes: number } | null;
}
export interface WorkflowInput {
  workflow_id: string;
  inputs: Record<string, unknown>;
  framework: WorkflowFramework;
}
export function isWorkflowActive(status: string): boolean {
  return status === "queued" || status === "running";
}
