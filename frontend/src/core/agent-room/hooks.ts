import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useLayoutEffect, useRef } from "react";

import { useAuth } from "@/core/auth/AuthProvider";
import { hasPermission } from "@/core/auth/permissions";

import { isStaticWebsiteOnly } from "../static-mode";

import {
  AGENT_ROOM_MESSAGES_QUERY_KEY,
  fetchAgentRoomEnabled,
  listAgentRoomMessages,
  postAgentRoomMessage,
} from "./api";
import type { AgentRoomMessage } from "./types";

const useClientLayoutEffect =
  typeof window === "undefined" ? useEffect : useLayoutEffect;

export function agentRoomMessagesQueryKey(ownerId: string | null) {
  return [...AGENT_ROOM_MESSAGES_QUERY_KEY, ownerId] as const;
}

function useOwnerFence(ownerId: string | null) {
  const currentOwner = useRef(ownerId);
  currentOwner.current = ownerId;
  useClientLayoutEffect(() => {
    currentOwner.current = ownerId;
    return () => {
      currentOwner.current = null;
    };
  }, [ownerId]);
  return currentOwner;
}

export function useAgentRoomAccess() {
  const auth = useAuth();
  const ownerId =
    !isStaticWebsiteOnly() &&
    !auth.isLoading &&
    auth.isAuthenticated &&
    auth.user?.system_role === "admin" &&
    auth.user.id.trim()
      ? auth.user.id
      : null;
  const currentOwner = useOwnerFence(ownerId);
  const access = useQuery({
    queryKey: ["agent-room", "access", ownerId],
    queryFn: async ({ signal }) => {
      if (!ownerId || currentOwner.current !== ownerId)
        throw new Error("Room access is unavailable.");
      const enabled = await fetchAgentRoomEnabled(ownerId, signal);
      if (signal.aborted || currentOwner.current !== ownerId)
        throw new Error("Room account changed during access discovery.");
      return enabled;
    },
    enabled: ownerId !== null,
    retry: false,
    staleTime: 0,
    refetchOnMount: true,
  });
  const enabled =
    ownerId !== null &&
    access.data === true &&
    hasPermission(auth.user, "threads:read");
  return {
    ownerId,
    enabled,
    canWrite: enabled && hasPermission(auth.user, "threads:write"),
    isLoading: auth.isLoading || (ownerId !== null && access.isPending),
  };
}

export function useAgentRoomMessages() {
  const access = useAgentRoomAccess();
  const currentOwner = useOwnerFence(access.enabled ? access.ownerId : null);
  const ownerId = access.ownerId;
  const query = useQuery<AgentRoomMessage[]>({
    queryKey: agentRoomMessagesQueryKey(ownerId),
    queryFn: async ({ signal }) => {
      if (!ownerId || currentOwner.current !== ownerId)
        throw new Error("Room access is unavailable.");
      const messages = await listAgentRoomMessages(ownerId, signal);
      if (signal.aborted || currentOwner.current !== ownerId)
        throw new Error("Room account changed during the read.");
      if (messages.some((message) => message.user_id !== ownerId))
        throw new Error("Room response does not match the signed-in account.");
      return messages;
    },
    enabled: access.enabled,
    retry: false,
    refetchInterval: 10_000,
  });
  // A disabled query can still expose cached data; gate the projection too.
  return { ...query, data: access.enabled ? query.data : undefined };
}

export function usePostAgentRoomMessage() {
  const access = useAgentRoomAccess();
  const currentOwner = useOwnerFence(access.canWrite ? access.ownerId : null);
  const ownerId = access.ownerId;
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ["agent-room", "post", ownerId],
    retry: false,
    mutationFn: async (input: Parameters<typeof postAgentRoomMessage>[0]) => {
      if (!ownerId || currentOwner.current !== ownerId)
        throw new Error("Room posting is unavailable.");
      const message = await postAgentRoomMessage(input, ownerId);
      if (currentOwner.current !== ownerId)
        throw new Error("Room account changed during the post.");
      if (message.user_id !== ownerId)
        throw new Error("Room response does not match the signed-in account.");
      return message;
    },
    onSuccess: (message) => {
      if (!ownerId || currentOwner.current !== ownerId) return;
      queryClient.setQueryData<AgentRoomMessage[]>(
        agentRoomMessagesQueryKey(ownerId),
        (previous) => [...(previous ?? []), message].slice(-100),
      );
    },
  });
}
