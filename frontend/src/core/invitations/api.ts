import { UnauthorizedError } from "@/core/api/errors";
import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

export type InviteRole = "member" | "admin" | "client";

export const INVITE_ROLES: readonly InviteRole[] = [
  "member",
  "admin",
  "client",
];

export type WorkspaceOption = {
  id: string;
  name: string;
  role: string;
};

export type WorkspacesResponse = {
  workspaces: WorkspaceOption[];
  active_workspace_id: string | null;
};

export type CreatedInvitation = {
  id: string;
  token: string;
  expires_at: string;
  email: string;
  workspace_name: string;
};

export type InviteFailureKind =
  | "frozen"
  | "forbidden"
  | "conflict"
  | "invalid_email"
  | "invalid"
  | "unavailable"
  | "network"
  | "unknown";

const INVITER_ROLES: ReadonlySet<string> = new Set(["owner", "admin"]);

export class InviteRequestError extends Error {
  readonly kind: InviteFailureKind;

  constructor(kind: InviteFailureKind) {
    super(`Invitation request failed: ${kind}`);
    this.name = "InviteRequestError";
    this.kind = kind;
  }
}

export function inviteTargets(
  workspaces: readonly WorkspaceOption[],
): WorkspaceOption[] {
  return workspaces.filter((workspace) => INVITER_ROLES.has(workspace.role));
}

export function defaultInviteWorkspaceId(
  targets: readonly WorkspaceOption[],
  activeWorkspaceId: string | null,
): string {
  if (activeWorkspaceId && targets.some((w) => w.id === activeWorkspaceId)) {
    return activeWorkspaceId;
  }
  return targets[0]?.id ?? "";
}

export function buildInviteLink(origin: string, token: string): string {
  return `${origin.replace(/\/+$/, "")}/invite#token=${token}`;
}

function detailMentionsEmail(detail: unknown): boolean {
  if (!Array.isArray(detail)) return false;
  return detail.some((item) => {
    const loc = (item as { loc?: unknown } | null)?.loc;
    return Array.isArray(loc) && loc.includes("email");
  });
}

export function classifyInviteFailure(
  status: number,
  detail: unknown,
): InviteFailureKind {
  if (status === 403) {
    return typeof detail === "string" && /paused/i.test(detail)
      ? "frozen"
      : "forbidden";
  }
  if (status === 409) return "conflict";
  if (status === 422) {
    return detailMentionsEmail(detail) ? "invalid_email" : "invalid";
  }
  if (status === 503) return "unavailable";
  return "unknown";
}

export async function loadInviteWorkspaces(
  signal?: AbortSignal,
): Promise<WorkspacesResponse> {
  const response = await fetch(`${getBackendBaseURL()}/api/workspaces`, {
    signal,
  });
  if (!response.ok) throw new Error("Workspace list request failed");
  return (await response.json()) as WorkspacesResponse;
}

export async function createInvitation(
  input: { organizationId: string; email: string; role: InviteRole },
  signal?: AbortSignal,
): Promise<CreatedInvitation> {
  let response: Response;
  try {
    response = await fetch(`${getBackendBaseURL()}/api/v1/auth/invitations`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        organization_id: input.organizationId,
        email: input.email,
        role: input.role,
      }),
      signal,
    });
  } catch (error) {
    if (error instanceof UnauthorizedError) throw error;
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }
    throw new InviteRequestError("network");
  }

  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as {
      detail?: unknown;
    };
    throw new InviteRequestError(
      classifyInviteFailure(response.status, body.detail),
    );
  }
  return (await response.json()) as CreatedInvitation;
}
