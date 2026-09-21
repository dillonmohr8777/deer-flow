import { z } from "zod";

import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";
import { safePluginIcon } from "@/core/mcp/icon";

const workspaceListSchema = z.object({
  workspaces: z.array(
    z.object({ id: z.string().min(1), name: z.string(), role: z.string() }),
  ),
  active_workspace_id: z.string().nullable(),
});
const brandingSchema = z.object({
  workspace_id: z.string().min(1),
  workspace_name: z.string(),
  brand_name: z.string().nullable(),
  logo: z
    .string()
    .nullable()
    .refine((value) => value === null || Boolean(safePluginIcon(value))),
  treatment: z.enum(["classic", "current", "paper"]),
  version: z.number().int().nonnegative(),
  updated_at: z.string().nullable(),
  can_edit: z.boolean(),
});
export type WorkspaceList = z.infer<typeof workspaceListSchema>;
export type WorkspaceBranding = z.infer<typeof brandingSchema>;
export type BrandingDraft = Pick<
  WorkspaceBranding,
  "brand_name" | "logo" | "treatment"
>;

export class WorkspaceBrandingError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "WorkspaceBrandingError";
  }
}

async function checked(response: Response) {
  if (response.ok) return response.json() as Promise<unknown>;
  const messages: Record<number, string> = {
    403: "You no longer have permission to edit this workspace’s branding.",
    404: "This shared workspace is no longer available to your account.",
    412: "A teammate changed the branding after you opened it. Load the latest version before saving again.",
    413: "The prepared logo is too large. Choose a smaller image.",
    415: "That logo could not be accepted. Choose a valid PNG, JPEG or WebP.",
    422: "Check the brand name. Use 1–120 characters, or leave it empty to use the workspace name.",
    503: "Workspace branding is temporarily unavailable. Your draft is still here.",
  };
  throw new WorkspaceBrandingError(
    response.status,
    messages[response.status] ??
      "Workspace branding could not be saved or loaded. Try again.",
  );
}

export async function listWorkspaces(
  signal?: AbortSignal,
): Promise<WorkspaceList> {
  return workspaceListSchema.parse(
    await checked(
      await fetch(`${getBackendBaseURL()}/api/workspaces`, { signal }),
    ),
  );
}

export async function readWorkspaceBranding(
  workspaceId: string,
  signal?: AbortSignal,
): Promise<WorkspaceBranding> {
  const data = brandingSchema.parse(
    await checked(
      await fetch(
        `${getBackendBaseURL()}/api/workspaces/${encodeURIComponent(workspaceId)}/branding`,
        { signal },
      ),
    ),
  );
  if (data.workspace_id !== workspaceId)
    throw new Error(
      "The branding response did not match the selected workspace.",
    );
  return data;
}

export async function saveWorkspaceBranding(
  workspaceId: string,
  draft: BrandingDraft,
  version: number,
): Promise<WorkspaceBranding> {
  const data = brandingSchema.parse(
    await checked(
      await fetch(
        `${getBackendBaseURL()}/api/workspaces/${encodeURIComponent(workspaceId)}/branding`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ...draft, expected_version: version }),
        },
      ),
    ),
  );
  if (data.workspace_id !== workspaceId)
    throw new Error(
      "The branding response did not match the selected workspace.",
    );
  return data;
}

export async function resetWorkspaceBranding(
  workspaceId: string,
  version: number,
): Promise<WorkspaceBranding> {
  const data = brandingSchema.parse(
    await checked(
      await fetch(
        `${getBackendBaseURL()}/api/workspaces/${encodeURIComponent(workspaceId)}/branding?expected_version=${version}`,
        { method: "DELETE" },
      ),
    ),
  );
  if (data.workspace_id !== workspaceId)
    throw new Error(
      "The branding response did not match the selected workspace.",
    );
  return data;
}
