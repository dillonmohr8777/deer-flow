import type { KnowledgeScopeSnapshot } from "@/core/knowledge";

export interface AgentModelSettings {
  temperature?: number | null;
  max_tokens?: number | null;
}

export type ReasoningEffort = "low" | "medium" | "high";

export interface Agent {
  name: string;
  display_name?: string | null;
  description: string;
  model: string | null;
  tool_groups: string[] | null;
  skills: string[] | null;
  mcp_plugins?: string[] | null;
  knowledge_scope?: KnowledgeScopeSnapshot | null;
  allowed_subagents?: string[] | null;
  model_settings?: AgentModelSettings | null;
  thinking_enabled?: boolean | null;
  reasoning_effort?: ReasoningEffort | null;
  soul?: string | null;
  /** Client this agent was stamped for, if any (fleet templates). */
  client_id?: string | null;
  /** Fleet template this agent was stamped from, if any. */
  template_id?: string | null;
  /** Version of the fleet template this agent was stamped from, if any. */
  template_version?: string | null;
}

export interface CreateAgentRequest {
  name: string;
  display_name?: string | null;
  description?: string;
  model?: string | null;
  tool_groups?: string[] | null;
  skills?: string[] | null;
  mcp_plugins?: string[] | null;
  knowledge_scope?: KnowledgeScopeSnapshot | null;
  allowed_subagents?: string[] | null;
  model_settings?: AgentModelSettings | null;
  thinking_enabled?: boolean | null;
  reasoning_effort?: ReasoningEffort | null;
  soul?: string;
}

export interface UpdateAgentRequest {
  display_name?: string | null;
  description?: string | null;
  model?: string | null;
  tool_groups?: string[] | null;
  skills?: string[] | null;
  mcp_plugins?: string[] | null;
  knowledge_scope?: KnowledgeScopeSnapshot | null;
  allowed_subagents?: string[] | null;
  model_settings?: AgentModelSettings | null;
  thinking_enabled?: boolean | null;
  reasoning_effort?: ReasoningEffort | null;
  soul?: string | null;
}
