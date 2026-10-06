export type ApprovalActionType =
  | "slack_message"
  | "email"
  | "ad_change"
  | "other";

export type ApprovalStatus =
  | "pending"
  | "approved"
  | "rejected"
  | "executed"
  | "failed";

export type FactCheckClaim = {
  id: number;
  text: string;
  raw: string;
  kind: string;
  verdict: "supported" | "contradicted" | "unsupported" | "unverifiable";
  reason: string;
  evidence: string | null;
  conflicting: string | null;
};

/** ``FactCheckReport.to_dict()`` (``deerflow/factcheck/core.py``). */
export type FactCheck = {
  gate: "block" | "flag" | "pass";
  counts: Record<string, number>;
  claims: FactCheckClaim[];
};

/** ``ApprovalResponse`` (``backend/app/gateway/routers/approvals.py``). */
export type Approval = {
  id: string;
  action_type: ApprovalActionType;
  title: string;
  target: string;
  payload: Record<string, unknown>;
  original_payload: Record<string, unknown>;
  status: ApprovalStatus;
  thread_id: string | null;
  run_id: string | null;
  agent_name: string | null;
  decided_by: string | null;
  decided_at: string | null;
  executed_at: string | null;
  execution_result: Record<string, unknown> | null;
  fact_check?: FactCheck | null;
  error: string | null;
  created_at: string;
  updated_at: string;
};

export type ApprovalEdit = {
  title?: string;
  target?: string;
  payload?: Record<string, unknown>;
};
