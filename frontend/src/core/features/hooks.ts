import { useQuery } from "@tanstack/react-query";

import {
  fetchBrowserControlEnabled,
  fetchConversationReferencesCapability,
  fetchDeskEnabled,
  fetchKnowledgeBaseFeature,
  fetchMcpTasksEnabled,
  fetchMomentumInternalEnabled,
  fetchSubagentBatchesCapability,
} from "./api";

export function useBrowserControlEnabled() {
  const { data, isPending } = useQuery({
    queryKey: ["features", "browser_control"],
    queryFn: () => fetchBrowserControlEnabled(),
    staleTime: 0,
    refetchOnMount: true,
    retry: false,
  });

  return {
    enabled: data ?? false,
    isLoading: isPending,
  };
}

export function useMcpTasksEnabled() {
  const { data, isPending } = useQuery({
    queryKey: ["features", "mcp_tasks"],
    queryFn: () => fetchMcpTasksEnabled(),
    staleTime: 0,
    refetchOnMount: true,
    retry: false,
  });

  return {
    enabled: data ?? false,
    isLoading: isPending,
  };
}

export function useSubagentBatchesCapability() {
  const { data, isPending } = useQuery({
    queryKey: ["features", "subagent_batches"],
    queryFn: () => fetchSubagentBatchesCapability(),
    staleTime: 0,
    refetchOnMount: true,
    retry: false,
  });
  return {
    repositoryAvailable: data?.repositoryAvailable ?? false,
    workerRunning: data?.workerRunning ?? false,
    maxRunning: data?.maxRunning ?? 0,
    isLoading: isPending,
  };
}

export function useConversationReferencesCapability() {
  const { data, isPending } = useQuery({
    queryKey: ["features", "conversation_references"],
    queryFn: () => fetchConversationReferencesCapability(),
    staleTime: 0,
    refetchOnMount: true,
    retry: false,
  });
  return {
    enabled: data?.enabled ?? false,
    maxReferences: data?.maxReferences ?? 0,
    isLoading: isPending,
  };
}

export function useKnowledgeBaseEnabled() {
  const { data, isPending } = useQuery({
    queryKey: ["features", "knowledge_base"],
    queryFn: fetchKnowledgeBaseFeature,
    staleTime: 0,
    refetchOnMount: true,
    retry: false,
  });
  return {
    scopeSelectionEnabled: data?.scopeSelectionEnabled ?? false,
    isLoading: isPending,
  };
}

export function useDeskEnabled() {
  const { data, isPending } = useQuery({
    queryKey: ["features", "desk"],
    queryFn: fetchDeskEnabled,
    staleTime: 0,
    refetchOnMount: true,
    retry: false,
  });
  return { enabled: data ?? false, isLoading: isPending };
}

/** Team channels and AI Academy: Momentum staff on the private instance only. */
export function useMomentumInternalEnabled() {
  const { data, isPending } = useQuery({
    queryKey: ["features", "momentum_internal"],
    queryFn: fetchMomentumInternalEnabled,
    staleTime: 0,
    refetchOnMount: true,
    retry: false,
  });
  return { enabled: data ?? false, isLoading: isPending };
}
