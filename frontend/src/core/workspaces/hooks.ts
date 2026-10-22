import { useIsMutating, useMutation, useQuery } from "@tanstack/react-query";

import { fetch } from "@/core/api/fetcher";

type WorkspaceList = {
  workspaces: { id: string; name: string; role: string }[];
  active_workspace_id: string | null;
  private_workspace_name?: string | null;
};

export function useWorkspaceSelection() {
  const query = useQuery({
    queryKey: ["workspaces"],
    queryFn: async ({ signal }): Promise<WorkspaceList> => {
      const response = await fetch("/api/workspaces", { signal });
      if (!response.ok) throw new Error("Workspace list unavailable");
      return response.json() as Promise<WorkspaceList>;
    },
  });
  const busy = useIsMutating({ mutationKey: ["workspace-selection"] }) > 0;
  const selection = useMutation({
    mutationKey: ["workspace-selection"],
    mutationFn: async (workspaceId: string | null) => {
      const response = await fetch("/api/workspaces/select", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workspace_id: workspaceId }),
      });
      if (!response.ok) {
        throw new Error("Couldn't switch workspace. Refresh and try again.");
      }
      // Discard cached data from the previous workspace before showing chats.
      window.location.assign("/workspace/chats");
    },
  });
  return {
    data: query.data,
    isLoading: query.isLoading,
    busy,
    error: selection.error ?? query.error,
    selectWorkspace: selection.mutateAsync,
  };
}
