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
  error: string | null;
  created_at: string;
  updated_at: string;
};

export type ApprovalEdit = {
  title?: string;
  target?: string;
  payload?: Record<string, unknown>;
};
