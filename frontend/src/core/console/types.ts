export type ConsoleStats = {
  total_runs: number;
  active_runs: number;
  failed_runs: number;
  total_threads: number;
  total_agents: number;
  total_tokens: number;
  total_cost: number | null;
  currency: string | null;
};

export type ConsoleRunItem = {
  run_id: string;
  thread_id: string;
  thread_title: string | null;
  assistant_id: string | null;
  status: string;
  model_name: string | null;
  created_at: string | null;
  updated_at: string | null;
  duration_seconds: number | null;
  total_tokens: number;
  message_count: number;
  cost: number | null;
  error: string | null;
};

export type ConsoleRunsResponse = { runs: ConsoleRunItem[]; has_more: boolean };

export type ConsoleUsageLedgerItem = {
  event_id: number;
  run_id: string;
  thread_id: string;
  organization_id: string | null;
  assistant_id: string | null;
  provider_attempt_id: string | null;
  llm_call_index: number | null;
  attempt_status: string;
  caller: string | null;
  provider: string | null;
  requested_model: string | null;
  resolved_model: string | null;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cache_read_tokens: number;
  latency_ms: number | null;
  provider_reported_cost: number | null;
  provider_reported_currency: string | null;
  estimated_cost: number | null;
  estimated_currency: string | null;
  error_type: string | null;
  created_at: string | null;
};

export type ConsoleUsageLedger = {
  attempts: ConsoleUsageLedgerItem[];
  has_more: boolean;
};

export type ConsoleUsageDay = {
  date: string;
  total_tokens: number;
  input_tokens: number;
  output_tokens: number;
  runs: number;
  cost: number;
};

export type ConsoleUsageModelBreakdown = {
  tokens: number;
  runs: number;
  cost: number | null;
  input_tokens: number;
  cache_read_tokens: number;
};

export type ConsoleUsage = {
  days: ConsoleUsageDay[];
  by_model: Record<string, ConsoleUsageModelBreakdown>;
  total_tokens: number;
  total_runs: number;
  total_cost: number | null;
  currency: string | null;
};
