import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useAuth } from "@/core/auth/AuthProvider";
import { isStaticWebsiteOnly } from "@/core/static-mode";

import {
  listWorkspaces,
  readWorkspaceBranding,
  resetWorkspaceBranding,
  saveWorkspaceBranding,
  type BrandingDraft,
} from "./api";

export function useWorkspaces() {
  const { user } = useAuth();
  return useQuery({
    queryKey: ["workspaces", user?.id ?? null],
    queryFn: ({ signal }) => listWorkspaces(signal),
    enabled: Boolean(user) && !isStaticWebsiteOnly(),
    retry: false,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });
}

export function useWorkspaceBranding() {
  const { user } = useAuth();
  const client = useQueryClient();
  const workspaces = useWorkspaces();
  const workspaceId = workspaces.data?.active_workspace_id ?? null;
  const workspace = workspaces.data?.workspaces.find(
    (item) => item.id === workspaceId,
  );
  const queryKey = ["workspace-branding", user?.id ?? null, workspaceId];
  const branding = useQuery({
    queryKey,
    queryFn: ({ signal }) => readWorkspaceBranding(workspaceId!, signal),
    enabled: Boolean(user && workspaceId && workspace),
    retry: false,
    staleTime: 30_000,
    refetchOnWindowFocus: true,
  });
  const save = useMutation({
    mutationFn: ({
      draft,
      version,
    }: {
      draft: BrandingDraft;
      version: number;
    }) => saveWorkspaceBranding(workspaceId!, draft, version),
    onSuccess: (data) => client.setQueryData(queryKey, data),
  });
  const reset = useMutation({
    mutationFn: (version: number) =>
      resetWorkspaceBranding(workspaceId!, version),
    onSuccess: (data) => client.setQueryData(queryKey, data),
  });
  return { workspaces, workspaceId, workspace, branding, save, reset };
}
