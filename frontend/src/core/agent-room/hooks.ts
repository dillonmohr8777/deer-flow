import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { isStaticWebsiteOnly } from "../static-mode";

import {
  AGENT_ROOM_MESSAGES_QUERY_KEY,
  listAgentRoomMessages,
  postAgentRoomMessage,
} from "./api";
import type { AgentRoomMessage } from "./types";

export function useAgentRoomMessages() {
  return useQuery<AgentRoomMessage[]>({
    queryKey: AGENT_ROOM_MESSAGES_QUERY_KEY,
    queryFn: listAgentRoomMessages,
    enabled: !isStaticWebsiteOnly(),
    refetchInterval: 10_000,
  });
}

export function usePostAgentRoomMessage() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: postAgentRoomMessage,
    onSuccess: (message) => {
      queryClient.setQueryData<AgentRoomMessage[]>(
        AGENT_ROOM_MESSAGES_QUERY_KEY,
        (previous) => [...(previous ?? []), message].slice(-100),
      );
    },
  });
}
