"use client";

import { useEffect, useState } from "react";

import { fetchTodayBrief } from "./api";
import type { TodayBrief } from "./types";

export type TodayBriefState =
  | { status: "loading" }
  | { status: "ready"; brief: TodayBrief }
  | { status: "error" };

/**
 * The Daily page has no QueryClientProvider or AuthProvider. It's public,
 * outside the workspace shell (see frontend/src/AGENTS.md's Momentum
 * Command Center notes), so this is a plain fetch-on-mount hook rather than
 * a TanStack Query one. Only fetches when `signedIn`; the caller resolves
 * that server-side (getDailyViewer()) so an anonymous reader never triggers
 * an authenticated request.
 */
export function useTodayBrief(signedIn: boolean): TodayBriefState {
  const [state, setState] = useState<TodayBriefState>({ status: "loading" });

  useEffect(() => {
    if (!signedIn) {
      return;
    }
    let cancelled = false;
    setState({ status: "loading" });
    fetchTodayBrief()
      .then((brief) => {
        if (!cancelled) setState({ status: "ready", brief });
      })
      .catch(() => {
        if (!cancelled) setState({ status: "error" });
      });
    return () => {
      cancelled = true;
    };
  }, [signedIn]);

  return state;
}
