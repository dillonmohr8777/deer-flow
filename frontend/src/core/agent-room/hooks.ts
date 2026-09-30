import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useLayoutEffect, useRef } from "react";

import { useAuth } from "@/core/auth/AuthProvider";
import { hasPermission } from "@/core/auth/permissions";

import { isStaticWebsiteOnly } from "../static-mode";

import {
  AGENT_ROOM_MESSAGES_QUERY_KEY,
  AgentRoomAccessDeniedError,
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
    refetchOnMount: "always",
    // A window refocus must not swap the page away from a live draft: a
    // background revalidation is handled by the sticky-admission logic
    // below instead of by refetching here at all.
    refetchOnWindowFocus: false,
  });

  // First admission for an owner requires a completed, successful fresh
  // discovery (the existing `refetchOnMount: "always"` + `staleTime: 0`
  // behavior below). Once granted, admission is sticky: a later background
  // refetch (reconnect, a manual refetch, ...) that merely fails -- a
  // network hiccup, a 5xx -- must not evict the composer or redirect away.
  // Only an explicit `false` result or a real access-denial error (403/404)
  // revokes it.
  const admittedOwner = useRef<string | null>(null);
  if (ownerId === null || currentOwner.current !== ownerId) {
    admittedOwner.current = null;
  } else if (!access.isFetching) {
    if (access.isSuccess && access.data === true) {
      admittedOwner.current = ownerId;
    } else if (
      access.data === false ||
      access.error instanceof AgentRoomAccessDeniedError
    ) {
      admittedOwner.current = null;
    }
  }
  const admitted = ownerId !== null && admittedOwner.current === ownerId;

  const enabled = admitted && hasPermission(auth.user, "threads:read");
  return {
    ownerId,
    enabled,
    canWrite: enabled && hasPermission(auth.user, "threads:write"),
    isLoading:
      auth.isLoading ||
      (ownerId !== null &&
        !admitted &&
        (access.isPending || access.isFetching)),
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
  const auth = useAuth();
  const access = useAgentRoomAccess();
  // Fenced on the raw signed-in identity, not on `canWrite`/`enabled`: those
  // are derived through `access`'s own admission state, which the read path
  // deliberately holds at `null`/`false` while merely uncertain (a
  // same-owner auth refresh in flight, a background access re-check). That
  // uncertainty is not an account change, so it must never trip this fence
  // and falsely fail (and duplicate on retry) an already-sent post.
  // `canWrite` is still the right gate for whether to send at all -- just
  // checked once, before sending, not re-derived after the await.
  const currentOwner = useOwnerFence(auth.user?.id.trim() ?? null);
  const ownerId = access.ownerId;
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ["agent-room", "post", ownerId],
    retry: false,
    mutationFn: async (input: Parameters<typeof postAgentRoomMessage>[0]) => {
      if (!ownerId || !access.canWrite || currentOwner.current !== ownerId)
        throw new Error("Room posting is unavailable.");
      const message = await postAgentRoomMessage(input, ownerId);
      if (currentOwner.current !== ownerId)
        throw new Error("Room account changed during the post.");
      if (message.user_id !== ownerId)
        throw new Error("Room response does not match the signed-in account.");
      return message;
    },
    onSuccess: (message) => {
      // Read from the ref and the server-confirmed message, never from the
      // `ownerId`/`access` closure: React Query calls onSuccess against
      // whatever render happened to be current when the mutation settled,
      // which can be one where `access.ownerId` is transiently `null` (the
      // same benign same-owner refresh the fence above must also ignore).
      if (currentOwner.current !== message.user_id) return;
      queryClient.setQueryData<AgentRoomMessage[]>(
        agentRoomMessagesQueryKey(message.user_id),
        (previous) => [...(previous ?? []), message].slice(-100),
      );
    },
  });
}
