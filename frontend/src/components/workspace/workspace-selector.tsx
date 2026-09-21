"use client";

import { useState } from "react";

import { fetch } from "@/core/api/fetcher";
import { useWorkspaces } from "@/core/workspaces/hooks";

export function WorkspaceSelector() {
  const workspaces = useWorkspaces();
  const data = workspaces.data;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function select(workspaceId: string) {
    setBusy(true);
    setError("");
    try {
      const response = await fetch("/api/workspaces/select", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ workspace_id: workspaceId || null }),
      });
      if (!response.ok)
        throw new Error("Could not switch workspace. Refresh and try again.");
      // A full navigation discards cached data from the previous workspace.
      window.location.assign("/workspace/command-center");
    } catch (cause: unknown) {
      setError(
        cause instanceof Error ? cause.message : "Could not switch workspace.",
      );
      setBusy(false);
    }
  }

  if (!data?.workspaces.length && !error && !workspaces.error) return null;
  return (
    <div className="px-2 pb-2">
      <label
        htmlFor="active-workspace"
        className="text-muted-foreground text-xs"
      >
        Workspace
      </label>
      <select
        id="active-workspace"
        className="bg-background mt-1 w-full rounded-md border px-2 py-2 text-sm"
        value={data?.active_workspace_id ?? ""}
        disabled={busy || !data}
        onChange={(event) => void select(event.target.value)}
      >
        <option value="">My private workspace</option>
        {data?.workspaces.map((workspace) => (
          <option key={workspace.id} value={workspace.id}>
            {workspace.name}
          </option>
        ))}
      </select>
      {(error || workspaces.error) && (
        <p role="alert" className="text-destructive mt-1 text-xs">
          {error || "Workspace list unavailable. Refresh to try again."}
        </p>
      )}
    </div>
  );
}
