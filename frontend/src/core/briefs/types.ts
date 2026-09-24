/** Mirrors backend/app/gateway/routers/briefs.py's response models. */

export type BriefClient = {
  id: string;
  display_name: string;
};

export type BriefActivityKind =
  | "thread"
  | "run_success"
  | "run_failed"
  | "document"
  | "scheduled_task_success"
  | "scheduled_task_failed";

export type BriefActivityItem = {
  kind: BriefActivityKind;
  title: string | null;
  detail: string | null;
  project_id: string | null;
  project_name: string | null;
  client_id: string | null;
  client_name: string | null;
  thread_id: string | null;
  agent_name: string | null;
  occurred_at: string;
};

export type BriefDueTask = {
  task_id: string;
  title: string;
  next_run_at: string;
  thread_id: string | null;
};

export type BriefWaitingKind = "interrupted" | "clarification";

export type BriefWaitingItem = {
  kind: BriefWaitingKind;
  thread_id: string;
  run_id: string;
  title: string | null;
  project_id: string | null;
  project_name: string | null;
  client_id: string | null;
  client_name: string | null;
  agent_name: string | null;
  updated_at: string;
};

export type TodayBrief = {
  generated_at: string;
  assigned_clients: BriefClient[];
  activity: BriefActivityItem[];
  due_today: BriefDueTask[];
  waiting_on_you: BriefWaitingItem[];
};
