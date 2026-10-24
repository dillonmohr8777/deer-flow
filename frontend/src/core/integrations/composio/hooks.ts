import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";

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

  const start = useCallback(() => {
    // Opened synchronously in the click so pop-up blockers allow it.
    const popup = window.open("", "momo-connect", "popup,width=520,height=720");
    if (!popup) {
      setPhase({
        kind: "error",
        message: "Allow pop-ups for MomoBot, then press Connect again.",
      });
      return;
    }
    setPhase({ kind: "working" });
    void (async () => {
      try {
        const attempt = handle ?? (await createConnectAttempt(toolkit)).handle;
        const result = await finishInPopup(popup, attempt);
        setPhase({ kind: "done", message: retryText(result.retry) });
        await queryClient.invalidateQueries({
          queryKey: COMPOSIO_STATUS_QUERY_KEY,
        });
        const source = result.retry.source_run_id;
        if (threadId && source && result.retry.state === "submitted") {
          // The receipt can be stored after run.end; read it the normal way.
          if (await hasConnectedReceipt(threadId, source, result.handle)) {
            await queryClient.invalidateQueries({
              queryKey: ["threads", threadId],
            });
          }
        }
      } catch (error) {
        if (!popup.closed) popup.close();
        const code = error instanceof Error ? error.message : String(error);
        setPhase({ kind: "error", message: reasonText(code) || code });
        await queryClient.invalidateQueries({
          queryKey: COMPOSIO_STATUS_QUERY_KEY,
        });
      }
    })();
  }, [handle, queryClient, threadId, toolkit]);

  return { phase, start };
}
