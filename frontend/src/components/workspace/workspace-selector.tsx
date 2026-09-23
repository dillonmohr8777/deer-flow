"use client";

import { useEffect, useState } from "react";

import { SidebarGroupLabel } from "@/components/ui/sidebar";

type WorkspaceList = {
  workspaces: { id: string; name: string; role: string }[];
  active_workspace_id: string | null;
};

export function WorkspaceSelector() {
  const [data, setData] = useState<WorkspaceList | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    void fetch("/api/workspaces", { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error("Workspace list unavailable");
        setData((await response.json()) as WorkspaceList);
      })
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) setError(String(cause));
      });
    return () => controller.abort();
  }, []);

  async function select(workspaceId: string) {
    setBusy(true);
    setError("");
    try {
      const csrf = /(?:^|;\s*)csrf_token=([^;]+)/.exec(document.cookie)?.[1];
      const response = await fetch("/api/workspaces/select", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(csrf ? { "X-CSRF-Token": decodeURIComponent(csrf) } : {}),
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

  if (!data?.workspaces.length && !error) return null;
  return (
    <div className="pb-2">
      {/* Same label voice as Projects and Recent chats. */}
      <SidebarGroupLabel asChild>
        <label htmlFor="active-workspace">Workspace</label>
      </SidebarGroupLabel>
      <select
        id="active-workspace"
        className="bg-card mx-2 w-[calc(100%-1rem)] rounded-md border px-2 py-2 text-sm"
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
      {error && (
        <p role="alert" className="text-destructive mx-2 mt-1 text-xs">
          {error}
        </p>
      )}
    </div>
  );
}
