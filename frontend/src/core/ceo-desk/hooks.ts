import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { isStaticWebsiteOnly } from "../static-mode";

import {
  CEO_DIGEST_QUERY_KEY,
  CEO_NEEDS_MY_YES_QUERY_KEY,
  CEO_SEATS_QUERY_KEY,
  ceoFeedQueryKey,
  getCeoFeed,
  getDailyDigest,
  getNeedsMyYes,
  getSeatRoster,
  postCeoFeedMessage,
  ratifySeat,
  reopenSeat,
} from "./api";
import type {
  CeoFeed,
  CeoFeedSlug,
  DailyDigest,
  NeedsMyYes,
  SeatRosterEntry,
} from "./types";

// Live feeds, not a chat: a short poll keeps #exec/#fleet current on the
// CEO Desk without a socket, matching core/team's own MESSAGE_POLL_MS.
const FEED_POLL_MS = 15_000;

export function useNeedsMyYes(enabled = true) {
  return useQuery<NeedsMyYes>({
    queryKey: CEO_NEEDS_MY_YES_QUERY_KEY,
    queryFn: getNeedsMyYes,
    // Static-demo mode has no Gateway; never fire this request there.
    enabled: enabled && !isStaticWebsiteOnly(),
  });
}

export function useSeatRoster(enabled = true) {
  return useQuery<SeatRosterEntry[]>({
    queryKey: CEO_SEATS_QUERY_KEY,
    queryFn: getSeatRoster,
    enabled: enabled && !isStaticWebsiteOnly(),
  });
}

export function useDailyDigest(enabled = true) {
  return useQuery<DailyDigest | null>({
    queryKey: CEO_DIGEST_QUERY_KEY,
    queryFn: getDailyDigest,
    enabled: enabled && !isStaticWebsiteOnly(),
  });
}

function useSeatAction(action: (seatId: string) => Promise<unknown>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: action,
    onSuccess: () => {
      // Ratifying/reopening a seat changes both the needs-my-yes queue (the
      // claim disappears) and the roster (its status/paused figure); refetch
      // both rather than hand-patching either cache.
      void queryClient.invalidateQueries({
        queryKey: CEO_NEEDS_MY_YES_QUERY_KEY,
      });
      void queryClient.invalidateQueries({ queryKey: CEO_SEATS_QUERY_KEY });
    },
  });
}

export function useRatifySeat() {
  return useSeatAction(ratifySeat);
}

export function useReopenSeat() {
  return useSeatAction(reopenSeat);
}

export function useCeoFeed(slug: CeoFeedSlug, enabled = true) {
  return useQuery<CeoFeed>({
    queryKey: ceoFeedQueryKey(slug),
    queryFn: () => getCeoFeed(slug),
    enabled: enabled && !isStaticWebsiteOnly(),
    refetchInterval: FEED_POLL_MS,
  });
}

export function usePostCeoFeedMessage(slug: CeoFeedSlug) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: string) => postCeoFeedMessage(slug, body),
    onSuccess: (message) => {
      queryClient.setQueryData<CeoFeed>(ceoFeedQueryKey(slug), (previous) =>
        previous
          ? {
              ...previous,
              exists: true,
              messages: [...previous.messages, message],
            }
          : { channel: slug, exists: true, messages: [message] },
      );
    },
  });
}
