import { useQuery } from "@tanstack/react-query";

import { useAuth } from "@/core/auth/AuthProvider";
import { isStaticWebsiteOnly } from "@/core/static-mode";

import { fetchBoard, fetchSpend } from "./api";

const REFRESH_MS = 30_000;

function useBoardQuery<T>(key: string, queryFn: () => Promise<T>) {
  const { user } = useAuth();
  return useQuery({
    // Scoped to the signed-in user so one account never reads another's cache.
    queryKey: ["command-center", user?.id ?? "anonymous", key],
    queryFn,
    enabled: Boolean(user) && !isStaticWebsiteOnly(),
    refetchInterval: REFRESH_MS,
    refetchIntervalInBackground: false,
    retry: false,
  });
}

export const useBoard = () => useBoardQuery("board", fetchBoard);
export const useSpend = () => useBoardQuery("spend", fetchSpend);
