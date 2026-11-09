import type { StatusTone } from "@/components/workspace/page-body";
import type {
  Approval,
  ApprovalActionType,
  ApprovalStatus,
} from "@/core/approvals";

export const STATUS_LABEL: Record<ApprovalStatus, string> = {
  pending: "Needs review",
  approved: "Approved",
  rejected: "Rejected",
  executed: "Sent",
  failed: "Failed",
};

export const TYPE_LABEL: Record<ApprovalActionType, string> = {
  slack_message: "Slack message",
  email: "Email",
  ad_change: "Ad change",
  deploy_report: "Report deploy",
  portal_publish: "Portal reply",
  social_post: "Social post",
  other: "Other",
};

export const STATUS_FILTERS: ReadonlyArray<{
  value: ApprovalStatus | "all";
  label: string;
}> = [
  { value: "pending", label: STATUS_LABEL.pending },
  { value: "executed", label: STATUS_LABEL.executed },
  { value: "approved", label: STATUS_LABEL.approved },
  { value: "failed", label: STATUS_LABEL.failed },
  { value: "rejected", label: STATUS_LABEL.rejected },
  { value: "all", label: "All" },
];

export function statusTone(status: ApprovalStatus): StatusTone {
  switch (status) {
    case "pending":
      return "attention";
    case "approved":
      return "active";
    case "executed":
      return "ok";
    case "failed":
      return "danger";
    case "rejected":
      return "idle";
  }
}

/** A link this page may render: same-origin path or http(s) URL only. */
function safeHref(value: unknown): string | null {
  if (typeof value !== "string") return null;
  if (value.startsWith("/") && !value.startsWith("//")) return value;
  return /^https?:\/\//.test(value) ? value : null;
}

/** Where a social post appears: its live link once published, else the page it will go to. */
export function socialPostLink(approval: Approval): string | null {
  if (approval.action_type !== "social_post") return null;
  return (
    safeHref(approval.execution_result?.live_url) ??
    safeHref(approval.payload.page_url)
  );
}

/** An approved row an adapter stubbed: reviewed, but nothing was sent. */
export function isReadyToSend(approval: Approval): boolean {
  return (
    approval.status === "approved" &&
    approval.execution_result?.state === "ready_to_send"
  );
}

/** The status tag text, with the wording each delivery uses. */
export function statusText(approval: Approval): string {
  if (isReadyToSend(approval)) return "Ready to send";
  if (approval.status === "executed") {
    if (approval.action_type === "portal_publish") return "Published in portal";
    if (approval.action_type === "social_post") return "Published";
  }
  return STATUS_LABEL[approval.status];
}

export type PayloadField = { key: string; label: string; multiline: boolean };

/** Which payload keys get their own input; anything else edits as JSON. */
export function fieldsFor(type: ApprovalActionType): PayloadField[] | null {
  switch (type) {
    case "slack_message":
      return [{ key: "text", label: "Message", multiline: true }];
    case "email":
      return [
        { key: "subject", label: "Subject", multiline: false },
        { key: "body", label: "Body", multiline: true },
      ];
    case "social_post":
      return [
        { key: "text", label: "Post", multiline: true },
        { key: "link", label: "Link (optional)", multiline: false },
      ];
    default:
      return null;
  }
}

export function targetLabel(type: ApprovalActionType): string {
  switch (type) {
    case "slack_message":
      return "Slack channel id";
    case "email":
      return "To";
    case "social_post":
      return "Appears on";
    default:
      return "Target";
  }
}
