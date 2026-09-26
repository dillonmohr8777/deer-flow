"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Textarea } from "@/components/ui/textarea";
import {
  EmptyState,
  ErrorState,
  FilterGroup,
  pageStyles,
  StatusTag,
  WorkingState,
} from "@/components/workspace/page-body";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import {
  useApproveBoardReply,
  useBoardMessages,
  useBoardThread,
  useBoardThreads,
  useCreateBoardThread,
  useDraftBoardReply,
  useSendBoardReply,
  type BoardThreadKind,
  type BoardThreadStatus,
} from "@/core/board";
import { useClients, useMyClients } from "@/core/clients";
import { useDeskEnabled } from "@/core/features";
import { cn } from "@/lib/utils";

import {
  KIND_LABEL,
  KIND_OPTIONS,
  STATUS_FILTERS,
  STATUS_LABEL,
  canApprove,
  canDraft,
  canSendReply,
  latestMomoDraft,
  sortThreadsByUpdated,
  statusTone,
} from "./board-data";

import styles from "./board.module.css";

/**
 * The Momo Board: client posts, tickets, concerns and DMs, in the Desk's
 * visual language. Renders only when features.desk.enabled (same flag,
 * same "private instance only" boundary as the Desk).
 */
export function Board() {
  const { enabled, isLoading } = useDeskEnabled();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && !enabled) router.replace("/workspace/command-center");
  }, [enabled, isLoading, router]);

  useEffect(() => {
    if (enabled) document.title = "Board | MomoBot";
  }, [enabled]);

  if (!enabled) {
    return <WorkingState label="Loading" className="m-8" />;
  }
  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody className={pageStyles.page}>
        <BoardBody />
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}

export function BoardBody() {
  const [statusFilter, setStatusFilter] = useState<BoardThreadStatus | "all">(
    "all",
  );
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const threads = useBoardThreads(
    statusFilter === "all" ? undefined : { status: statusFilter },
  );
  const clients = useClients();
  const clientName = useMemo(() => {
    const byId = new Map(
      (clients.data ?? []).map((c) => [c.id, c.display_name]),
    );
    return (clientId: string | null) =>
      clientId ? (byId.get(clientId) ?? clientId) : "No client";
  }, [clients.data]);

  const sorted = useMemo(
    () => (threads.data ? sortThreadsByUpdated(threads.data) : []),
    [threads.data],
  );

  useEffect(() => {
    // Skip while a fetch is in flight: a just-created thread's list refetch
    // (invalidated by useCreateBoardThread's onSuccess) briefly still holds
    // the pre-create list, and clearing selectedId on that stale snapshot
    // would drop the very thread the caller just started and selected.
    if (
      selectedId &&
      !threads.isFetching &&
      !sorted.some((t) => t.id === selectedId)
    ) {
      setSelectedId(null);
    }
  }, [selectedId, sorted, threads.isFetching]);

  return (
    <div className={styles.frame} data-testid="board">
      <header className={styles.pageHead}>
        <div>
          <p className={pageStyles.eyebrow}>Momo Board</p>
          <h1 className="mt-1">Board</h1>
          <p className={cn(pageStyles.lede, "mt-1")}>
            Every client post, ticket, concern and DM, with Momo&apos;s drafts
            waiting on your review.
          </p>
        </div>
        <Button
          variant={showCreate ? "outline" : "default"}
          onClick={() => setShowCreate((v) => !v)}
        >
          {showCreate ? "Cancel" : "New thread"}
        </Button>
      </header>
      {showCreate ? (
        <NewThreadForm
          onCreated={(id) => {
            setSelectedId(id);
            setShowCreate(false);
          }}
          onCancel={() => setShowCreate(false)}
        />
      ) : null}
      <FilterGroup
        label="Status"
        showLabel
        value={statusFilter}
        onChange={setStatusFilter}
        options={STATUS_FILTERS}
      />
      <div className={styles.layout}>
        <div className={styles.list} aria-label="Threads">
          {threads.isError ? (
            <ErrorState
              message="Couldn't load board threads."
              detail={threads.error.message}
              action={
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => void threads.refetch()}
                >
                  Try again
                </Button>
              }
            />
          ) : threads.isLoading ? (
            <WorkingState label="Loading threads" />
          ) : sorted.length === 0 ? (
            <EmptyState momo="lead" title="Nothing here">
              {statusFilter === "all"
                ? "No board threads yet. Client posts, tickets, concerns and DMs will show up here."
                : `No threads with status "${STATUS_LABEL[statusFilter]}".`}
            </EmptyState>
          ) : (
            <ul className={styles.threadList}>
              {sorted.map((thread) => (
                <li key={thread.id}>
                  <button
                    type="button"
                    className={styles.threadRow}
                    aria-current={thread.id === selectedId}
                    onClick={() => setSelectedId(thread.id)}
                  >
                    <span className={styles.threadSubject}>
                      {thread.subject || KIND_LABEL[thread.kind]}
                    </span>
                    <span className={styles.threadMeta}>
                      <span>{clientName(thread.client_id)}</span>
                      <span>{KIND_LABEL[thread.kind]}</span>
                    </span>
                    <StatusTag tone={statusTone(thread.status)}>
                      {STATUS_LABEL[thread.status]}
                    </StatusTag>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className={styles.detail}>
          {selectedId ? (
            <ThreadDetail threadId={selectedId} clientName={clientName} />
          ) : (
            <EmptyState momo="qa" title="Pick a thread">
              Select a thread from the list to read it and, if Momo has a draft
              ready, review it here.
            </EmptyState>
          )}
        </div>
      </div>
    </div>
  );
}

/**
 * Start a post, ticket, concern or DM. The client picker is scoped to the
 * caller's own clients (``/api/clients/mine``): a client contact starting a
 * thread never sees the rest of the org's client roster to do it.
 */
function NewThreadForm({
  onCreated,
  onCancel,
}: {
  onCreated: (threadId: string) => void;
  onCancel: () => void;
}) {
  const myClients = useMyClients();
  const createMutation = useCreateBoardThread();

  const options = useMemo(() => myClients.data ?? [], [myClients.data]);
  const [clientId, setClientId] = useState("");
  const [kind, setKind] = useState<BoardThreadKind>("post");
  const [subject, setSubject] = useState("");

  useEffect(() => {
    if (!clientId && options.length > 0) {
      setClientId(options[0]!.id);
    }
  }, [clientId, options]);

  return (
    <div className={styles.actionPanel} aria-label="New thread">
      {myClients.isLoading ? (
        <WorkingState label="Loading your clients" />
      ) : options.length === 0 ? (
        <p className={styles.muted}>
          You aren&apos;t assigned to any client yet, so there&apos;s nowhere to
          start a thread.
        </p>
      ) : (
        <>
          <div className={styles.formRow}>
            <label htmlFor="board-new-client" className={pageStyles.eyebrow}>
              Client
            </label>
            <select
              id="board-new-client"
              className={styles.select}
              value={clientId}
              onChange={(event) => setClientId(event.target.value)}
            >
              {options.map((client) => (
                <option key={client.id} value={client.id}>
                  {client.display_name}
                </option>
              ))}
            </select>
          </div>
          <div className={styles.formRow}>
            <label htmlFor="board-new-kind" className={pageStyles.eyebrow}>
              Kind
            </label>
            <select
              id="board-new-kind"
              className={styles.select}
              value={kind}
              onChange={(event) =>
                setKind(event.target.value as BoardThreadKind)
              }
            >
              {KIND_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
          <div className={styles.formRow}>
            <label htmlFor="board-new-subject" className={pageStyles.eyebrow}>
              Subject
            </label>
            <Input
              id="board-new-subject"
              value={subject}
              onChange={(event) => setSubject(event.target.value)}
              placeholder="What's this about?"
            />
          </div>
          {createMutation.isError ? (
            <p className={styles.errorText}>{createMutation.error.message}</p>
          ) : null}
          <div className={styles.formActions}>
            <Button
              variant="outline"
              type="button"
              onClick={onCancel}
              disabled={createMutation.isPending}
            >
              Cancel
            </Button>
            <Button
              disabled={!clientId || createMutation.isPending}
              onClick={() =>
                createMutation.mutate(
                  { clientId, kind, subject },
                  { onSuccess: (thread) => onCreated(thread.id) },
                )
              }
            >
              {createMutation.isPending ? "Starting..." : "Start thread"}
            </Button>
          </div>
        </>
      )}
    </div>
  );
}

function ThreadDetail({
  threadId,
  clientName,
}: {
  threadId: string;
  clientName: (clientId: string | null) => string;
}) {
  const thread = useBoardThread(threadId);
  const messages = useBoardMessages(threadId);
  const draftMutation = useDraftBoardReply();
  const approveMutation = useApproveBoardReply();
  const sendMutation = useSendBoardReply();

  const [draftText, setDraftText] = useState("");
  const [replyText, setReplyText] = useState("");
  const [replySeededFor, setReplySeededFor] = useState<string | null>(null);

  const draft = messages.data ? latestMomoDraft(messages.data) : undefined;
  useEffect(() => {
    if (draft && replySeededFor !== draft.id) {
      setReplyText(draft.body);
      setReplySeededFor(draft.id);
    }
  }, [draft, replySeededFor]);

  if (thread.isError) {
    return (
      <ErrorState
        message="Couldn't load this thread."
        detail={thread.error.message}
        action={
          <Button
            variant="outline"
            size="sm"
            onClick={() => void thread.refetch()}
          >
            Try again
          </Button>
        }
      />
    );
  }
  if (thread.isLoading || !thread.data) {
    return <WorkingState label="Loading thread" />;
  }
  const status = thread.data.status;

  return (
    <div className={styles.threadDetail} data-testid="board-thread">
      <header className={styles.threadHead}>
        <div className="min-w-0">
          <h2>{thread.data.subject || KIND_LABEL[thread.data.kind]}</h2>
          <p className={styles.muted}>
            {clientName(thread.data.client_id)} &middot;{" "}
            {KIND_LABEL[thread.data.kind]}
          </p>
        </div>
        <StatusTag tone={statusTone(status)}>{STATUS_LABEL[status]}</StatusTag>
      </header>

      {messages.isError ? (
        <ErrorState
          message="Couldn't load messages."
          detail={messages.error.message}
        />
      ) : messages.isLoading ? (
        <WorkingState label="Loading messages" />
      ) : (
        <ScrollArea className={styles.messages}>
          <ul className={styles.messageList}>
            {(messages.data ?? []).map((message) => (
              <li
                key={message.id}
                className={cn(
                  styles.message,
                  styles[`message-${message.author_kind}`],
                )}
              >
                <span className={styles.messageAuthor}>
                  {message.author_kind === "client"
                    ? "Client"
                    : message.author_kind === "momo"
                      ? "Momo (draft)"
                      : "Owner"}
                </span>
                <p>{message.body}</p>
              </li>
            ))}
            {(messages.data?.length ?? 0) === 0 ? (
              <li className={styles.muted}>No messages yet.</li>
            ) : null}
          </ul>
        </ScrollArea>
      )}

      {canDraft(status) ? (
        <div className={styles.actionPanel} aria-label="Draft editor">
          <label htmlFor="board-draft" className={pageStyles.eyebrow}>
            Draft a reply
          </label>
          <Textarea
            id="board-draft"
            value={draftText}
            onChange={(event) => setDraftText(event.target.value)}
            placeholder="What should Momo say back?"
            rows={4}
          />
          {draftMutation.isError ? (
            <p className={styles.errorText}>{draftMutation.error.message}</p>
          ) : null}
          <Button
            disabled={!draftText.trim() || draftMutation.isPending}
            onClick={() =>
              draftMutation.mutate(
                { threadId, body: draftText },
                { onSuccess: () => setDraftText("") },
              )
            }
          >
            {draftMutation.isPending ? "Saving draft..." : "Save draft"}
          </Button>
        </div>
      ) : null}

      {canApprove(status) ? (
        <div className={styles.actionPanel} aria-label="Approve draft">
          <p className={pageStyles.eyebrow}>Momo&apos;s draft is ready</p>
          {approveMutation.isError ? (
            <p className={styles.errorText}>{approveMutation.error.message}</p>
          ) : null}
          <Button
            disabled={approveMutation.isPending}
            onClick={() => approveMutation.mutate({ threadId })}
          >
            {approveMutation.isPending ? "Approving..." : "Approve"}
          </Button>
        </div>
      ) : null}

      {canSendReply(status) ? (
        <div className={styles.actionPanel} aria-label="Send reply">
          <label htmlFor="board-reply" className={pageStyles.eyebrow}>
            Approved &mdash; send it
          </label>
          <Textarea
            id="board-reply"
            value={replyText}
            onChange={(event) => setReplyText(event.target.value)}
            rows={4}
          />
          {sendMutation.isError ? (
            <p className={styles.errorText}>{sendMutation.error.message}</p>
          ) : null}
          <Button
            disabled={!replyText.trim() || sendMutation.isPending}
            onClick={() => sendMutation.mutate({ threadId, body: replyText })}
          >
            {sendMutation.isPending ? "Sending..." : "Send reply"}
          </Button>
        </div>
      ) : null}

      {status === "replied" || status === "closed" ? (
        <p className={styles.muted}>
          {status === "replied" ? "Reply sent." : "Thread closed."}
        </p>
      ) : null}
    </div>
  );
}
