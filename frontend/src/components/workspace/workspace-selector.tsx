"use client";

import { SidebarGroupLabel } from "@/components/ui/sidebar";
import { useWorkspaceSelection } from "@/core/workspaces/hooks";

export function WorkspaceSelector() {
  const { data, busy, error, selectWorkspace } = useWorkspaceSelection();

  if (!data?.workspaces.length && !error) return null;
  return (
    <div className="pb-2">
      <SidebarGroupLabel asChild>
        <label htmlFor="active-workspace">Workspace</label>
      </SidebarGroupLabel>
      <select
        id="active-workspace"
        className="bg-card mx-2 w-[calc(100%-1rem)] rounded-md border px-2 py-2 text-sm"
        value={data?.active_workspace_id ?? ""}
        disabled={busy || !data}
        onChange={(event) => {
          void selectWorkspace(event.target.value || null).catch(
            () => undefined,
          );
        }}
      >
        <option value="">My private workspace</option>
        {data?.workspaces.map((workspace) => (
          <option key={workspace.id} value={workspace.id}>
            {workspace.name}
          </option>
        ))}
      </select>
      {error && (
        <p role="alert" className="text-destructive mx-2 mt-1 text-xs">
          {error.message}
        </p>
      )}
    </div>
  );
}
