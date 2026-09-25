import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { isStaticWebsiteOnly } from "../static-mode";

import {
  BOARD_THREADS_QUERY_KEY,
  approveBoardReply,
  boardMessagesQueryKey,
  boardThreadQueryKey,
  draftBoardReply,
  getBoardThread,
  listBoardMessages,
  listBoardThreads,
  sendBoardReply,
} from "./api";
import type { BoardThread, BoardThreadStatus } from "./types";

export function useBoardThreads(params?: {
  clientId?: string;
  status?: BoardThreadStatus;
}) {
  return useQuery<BoardThread[]>({
    queryKey: [
      ...BOARD_THREADS_QUERY_KEY,
      params?.clientId ?? null,
      params?.status ?? null,
    ],
    queryFn: () => listBoardThreads(params),
    // Static-demo mode has no Gateway; never fire this request there.
    enabled: !isStaticWebsiteOnly(),
  });
}

export function useBoardThread(threadId: string | null) {
  return useQuery<BoardThread>({
    queryKey: boardThreadQueryKey(threadId ?? ""),
    queryFn: () => getBoardThread(threadId!),
    enabled: !isStaticWebsiteOnly() && !!threadId,
  });
}

export function useBoardMessages(threadId: string | null) {
  return useQuery({
    queryKey: boardMessagesQueryKey(threadId ?? ""),
    queryFn: () => listBoardMessages(threadId!),
    enabled: !isStaticWebsiteOnly() && !!threadId,
  });
}

function useBoardThreadMutation(
  mutationFn: (threadId: string, body?: string) => Promise<BoardThread>,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ threadId, body }: { threadId: string; body?: string }) =>
      mutationFn(threadId, body),
    onSuccess: (thread) => {
      queryClient.setQueryData(boardThreadQueryKey(thread.id), thread);
      void queryClient.invalidateQueries({
        queryKey: boardMessagesQueryKey(thread.id),
      });
      void queryClient.invalidateQueries({ queryKey: BOARD_THREADS_QUERY_KEY });
    },
  });
}

export function useDraftBoardReply() {
  return useBoardThreadMutation((threadId, body) =>
    draftBoardReply(threadId, body ?? ""),
  );
}

export function useApproveBoardReply() {
  return useBoardThreadMutation((threadId) => approveBoardReply(threadId));
}

export function useSendBoardReply() {
  return useBoardThreadMutation((threadId, body) =>
    sendBoardReply(threadId, body ?? ""),
  );
}
