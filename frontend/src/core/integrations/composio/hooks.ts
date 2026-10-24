import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

import { invalidateStoppedThreadCaches } from "@/core/threads/hooks";

import {
  COMPOSIO_STATUS_QUERY_KEY,
  createConnectAttempt,
  finishInPopup,
  hasConnectedReceipt,
  loadToolkitStatus,
  reasonText,
  retryText,
} from "./api";

export function useToolkitStatus() {
  const query = useQuery({
    queryKey: COMPOSIO_STATUS_QUERY_KEY,
    queryFn: ({ signal }) => loadToolkitStatus(signal),
    retry: false,
  });
  const { refetch } = query;
  // People often finish signing in from another tab; recheck when they return.
  useEffect(() => {
    const onFocus = () => void refetch();
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [refetch]);
  return query;
}

export type ConnectPhase =
  | { kind: "idle" }
  | { kind: "working" }
  | { kind: "done"; message: string }
  | { kind: "error"; message: string };

/**
 * One connect flow. Pass ``handle`` when a tool already minted the attempt
 * (in-chat prompt); otherwise a fresh attempt is created for ``toolkit``.
 * ``threadId`` lets a retried step refresh its thread once the receipt lands.
 *
 * A tool-minted handle is single use: after any failure the next press starts
 * a fresh attempt with no retry intent, and the person is told to ask MomoBot
 * again. The browser never replays the waiting step itself.
 */
export function useConnect({
  toolkit,
  handle,
  threadId,
}: {
  toolkit: string;
  handle?: string;
  threadId?: string;
}) {
  const queryClient = useQueryClient();
  const [phase, setPhase] = useState<ConnectPhase>({ kind: "idle" });
  const toolHandle = useRef(handle);

  const start = useCallback(() => {
    // Its own window per attempt, opened synchronously so blockers allow it.
    const popup = window.open("", "_blank", "popup,width=520,height=720");
    if (!popup) {
      setPhase({
        kind: "error",
        message: "Allow pop-ups for MomoBot, then press Connect again.",
      });
      return;
    }
    setPhase({ kind: "working" });
    const fromTool = toolHandle.current;
    void (async () => {
      try {
        const attempt = fromTool
          ? { handle: fromTool, toolkit }
          : await createConnectAttempt(toolkit);
        const result = await finishInPopup(popup, attempt);
        setPhase({ kind: "done", message: retryText(result.retry) });
        await queryClient.invalidateQueries({
          queryKey: COMPOSIO_STATUS_QUERY_KEY,
        });
        const source = result.retry.source_run_id;
        if (threadId && source && result.retry.state === "submitted") {
          // The receipt can be stored after run.end; read it the normal way,
          // then let the chat's own run/history queries pick up the retry.
          if (await hasConnectedReceipt(threadId, source, result.handle)) {
            invalidateStoppedThreadCaches(queryClient, threadId);
          }
        }
      } catch (error) {
        if (!popup.closed) popup.close();
        toolHandle.current = undefined;
        const code = error instanceof Error ? error.message : String(error);
        const text = reasonText(code) || code;
        setPhase({
          kind: "error",
          message: fromTool
            ? `${text} After you connect, ask MomoBot to try that step again.`
            : text,
        });
        await queryClient.invalidateQueries({
          queryKey: COMPOSIO_STATUS_QUERY_KEY,
        });
      }
    })();
  }, [queryClient, threadId, toolkit]);

  return { phase, start };
}
