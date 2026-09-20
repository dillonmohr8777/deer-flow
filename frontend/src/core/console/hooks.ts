import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useAuth } from "@/core/auth/AuthProvider";
import { hasPermission } from "@/core/auth/permissions";

import {
  cancelConsoleRun,
  fetchConsoleRuns,
  fetchConsoleStats,
  fetchConsoleUsage,
} from "./api";

const RUNS_READ = "runs:read";
export const consoleQueryKey = (userId: string) => ["console", userId] as const;
export const consoleRunsQueryKey = (
  userId: string,
  status?: string,
  offset = 0,
) => [...consoleQueryKey(userId), "runs", status ?? null, offset] as const;

function canRead(user: ReturnType<typeof useAuth>["user"]) {
  return Boolean(user) && hasPermission(user, RUNS_READ);
}

export function useConsoleStats() {
  const { user } = useAuth();
  const enabled = canRead(user);
  return useQuery({
    queryKey: [
      ...(user ? consoleQueryKey(user.id) : ["console", "anonymous"]),
      "stats",
    ],
    queryFn: fetchConsoleStats,
    enabled,
    refetchInterval: enabled ? 30_000 : false,
    refetchIntervalInBackground: false,
  });
}

export function useConsoleRuns(
  options: { status?: string; offset?: number } = {},
) {
  const { user } = useAuth();
  const offset = options.offset ?? 0;
  const enabled = canRead(user);
  return useQuery({
    queryKey: user
      ? consoleRunsQueryKey(user.id, options.status, offset)
      : ["console", "anonymous", "runs", options.status ?? null, offset],
    queryFn: () => fetchConsoleRuns(options),
    enabled,
    refetchInterval: (query) => {
      if (!enabled || offset > 0) return false;
      const active = query.state.data?.runs.some(
        (run) => run.status === "pending" || run.status === "running",
      );
      return active ? 10_000 : 30_000;
    },
    refetchIntervalInBackground: false,
  });
}

export function useConsoleUsage() {
  const { user } = useAuth();
  const enabled = canRead(user);
  return useQuery({
    queryKey: [
      ...(user ? consoleQueryKey(user.id) : ["console", "anonymous"]),
      "usage",
    ],
    queryFn: fetchConsoleUsage,
    enabled,
    refetchIntervalInBackground: false,
  });
}

export function useCancelConsoleRun() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ threadId, runId }: { threadId: string; runId: string }) =>
      cancelConsoleRun(threadId, runId),
    onSuccess: (_data, { threadId }) => {
      if (user)
        void queryClient.invalidateQueries({
          queryKey: consoleQueryKey(user.id),
        });
      void queryClient.invalidateQueries({ queryKey: ["thread", threadId] });
    },
  });
}
