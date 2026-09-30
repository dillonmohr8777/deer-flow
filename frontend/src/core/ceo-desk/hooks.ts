import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { isStaticWebsiteOnly } from "../static-mode";

import {
  CEO_DIGEST_QUERY_KEY,
  CEO_NEEDS_MY_YES_QUERY_KEY,
  CEO_SEATS_QUERY_KEY,
  getDailyDigest,
  getNeedsMyYes,
  getSeatRoster,
  ratifySeat,
  reopenSeat,
} from "./api";
import type { DailyDigest, NeedsMyYes, SeatRosterEntry } from "./types";

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
