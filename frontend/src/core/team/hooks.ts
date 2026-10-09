import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { isStaticWebsiteOnly } from "../static-mode";

import {
  TEAM_CHANNELS_QUERY_KEY,
  TEAM_MEMBERS_QUERY_KEY,
  createTeamChannel,
  listTeamChannels,
  listTeamMembers,
  listTeamMessages,
  postTeamMessage,
  teamMessagesQueryKey,
} from "./api";
import type { TeamChannel, TeamMember, TeamMessage } from "./types";

// Light polling keeps a channel current without a socket; the board is a
// side channel, not a live chat, so 15 seconds is plenty.
const MESSAGE_POLL_MS = 15_000;

export function useTeamChannels(enabled = true) {
  return useQuery<TeamChannel[]>({
    queryKey: TEAM_CHANNELS_QUERY_KEY,
    queryFn: listTeamChannels,
    // Static-demo mode has no Gateway; never fire this request there.
    enabled: enabled && !isStaticWebsiteOnly(),
  });
}

export function useTeamMembers(enabled = true) {
  return useQuery<TeamMember[]>({
    queryKey: TEAM_MEMBERS_QUERY_KEY,
    queryFn: listTeamMembers,
    enabled: enabled && !isStaticWebsiteOnly(),
  });
}

export function useTeamMessages(channelId: string | null) {
  return useQuery<TeamMessage[]>({
    queryKey: teamMessagesQueryKey(channelId ?? ""),
    queryFn: () => listTeamMessages(channelId!),
    enabled: !isStaticWebsiteOnly() && !!channelId,
    refetchInterval: MESSAGE_POLL_MS,
  });
}

export function usePostTeamMessage() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ channelId, body }: { channelId: string; body: string }) =>
      postTeamMessage(channelId, body),
    onSuccess: (message) => {
      queryClient.setQueryData<TeamMessage[]>(
        teamMessagesQueryKey(message.channel_id),
        (previous) => [...(previous ?? []), message],
      );
    },
  });
}

export function useCreateTeamChannel() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createTeamChannel,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: TEAM_CHANNELS_QUERY_KEY });
    },
  });
}
