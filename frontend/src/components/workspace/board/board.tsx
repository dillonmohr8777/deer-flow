"use client";

import { ArrowLeftIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
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
  useDraftBoardReply,
  useSendBoardReply,
  type BoardThread,
  type BoardThreadStatus,
} from "@/core/board";
import { useClients } from "@/core/clients";
import { useDeskEnabled } from "@/core/features";
import { formatTimeAgo } from "@/core/utils/datetime";
import { cn } from "@/lib/utils";

import {
  KIND_LABEL,
  STATUS_FILTERS,
  STATUS_LABEL,
  authorLabel,
  canApprove,
  canDraft,
  canSendReply,
  conversationMessages,
  isDecided,
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

/** Phones and narrow tablets show one pane at a time: the slips or a thread. */
const ONE_PANE = "(max-width: 63.99rem)";

function shortDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
  }).format(date);
}

function fullDate(iso: string): string | undefined {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return undefined;
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

/**
 * A thread's state. Open states are a plain tag; a recorded decision
 * (approved, replied, closed) is an ink stamp, dated once it is final.
 */
function ThreadStatus({ thread }: { thread: BoardThread }) {
  const { status } = thread;
  if (!isDecided(status)) {
    return (
      <StatusTag tone={statusTone(status)}>{STATUS_LABEL[status]}</StatusTag>
    );
  }
  const date = status === "approved" ? "" : shortDate(thread.updated_at);
  return (
    <StatusTag tone={statusTone(status)} className={styles.stamp}>
      {STATUS_LABEL[status]}
      {date ? (
        <>
          <span className="sr-only">, </span>
          <span className={styles.stampDate}>{date}</span>
        </>
      ) : null}
    </StatusTag>
  );
}

export function BoardBody() {
  const [statusFilter, setStatusFilter] = useState<BoardThreadStatus | "all">(
    "all",
  );
  const [selectedId, setSelectedId] = useState<string | null>(null);
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
    if (selectedId && !sorted.some((t) => t.id === selectedId)) {
      setSelectedId(null);
    }
  }, [selectedId, sorted]);

  // On one-pane widths the slip that opened a thread is hidden while the
  // thread is open, so going back returns focus to it.
  const returnFocusTo = useRef<string | null>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const closeThread = () => {
    const id = selectedId;
    setSelectedId(null);
    returnFocusTo.current = id;
  };
  useEffect(() => {
    if (selectedId !== null || !returnFocusTo.current) return;
    const slip = listRef.current?.querySelector<HTMLButtonElement>(
      `[data-thread-id="${CSS.escape(returnFocusTo.current)}"]`,
    );
    slip?.focus();
    returnFocusTo.current = null;
  }, [selectedId]);

  return (
    <div
      className={styles.frame}
      data-testid="board"
      data-open={selectedId ? "thread" : "list"}
    >
      <header className={styles.pageHead}>
        <p className={pageStyles.eyebrow}>Momo Board</p>
        <h1 className="mt-1">Board</h1>
        <p className={cn(pageStyles.lede, "mt-1")}>
          Every client post, ticket, concern and DM, with Momo&apos;s drafts
          waiting on your review.
        </p>
      </header>
      <FilterGroup
        label="Status"
        showLabel
        value={statusFilter}
        onChange={setStatusFilter}
        options={STATUS_FILTERS}
        className={styles.filters}
      />
      <div className={styles.layout}>
        <section className={styles.list} aria-label="Threads">
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
            <ul className={styles.slips} ref={listRef}>
              {sorted.map((thread) => {
                const subject = thread.subject || KIND_LABEL[thread.kind];
                return (
                  <li key={thread.id}>
                    <button
                      type="button"
                      className={cn(styles.slip, "paper-card")}
                      data-thread-id={thread.id}
                      aria-current={thread.id === selectedId}
                      onClick={() => setSelectedId(thread.id)}
                    >
                      <span className={styles.slipMeta}>
                        <span className={styles.kind}>
                          {KIND_LABEL[thread.kind]}
                        </span>
                        <span className={styles.slipClient}>
                          {clientName(thread.client_id)}
                        </span>
                        <time
                          className={styles.slipTime}
                          dateTime={thread.updated_at}
                          title={fullDate(thread.updated_at)}
                        >
                          {formatTimeAgo(thread.updated_at)}
                        </time>
                      </span>
                      <span className={styles.slipSubject} title={subject}>
                        {subject}
                      </span>
                      <span className={styles.slipStatus}>
                        <ThreadStatus thread={thread} />
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </section>
        <div className={styles.detail}>
          {selectedId ? (
            <ThreadDetail
              key={selectedId}
              threadId={selectedId}
              clientName={clientName}
              onBack={closeThread}
            />
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

function ThreadDetail({
  threadId,
  clientName,
  onBack,
}: {
  threadId: string;
  clientName: (clientId: string | null) => string;
  onBack: () => void;
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

  // One pane at a time on phones: the slip that opened this is now hidden,
  // so focus moves into the pane. Until the thread has loaded (or when it
  // fails) the way back takes it; once loaded, the thread's heading does.
  const headingRef = useRef<HTMLHeadingElement>(null);
  const backRef = useRef<HTMLButtonElement>(null);
  const loaded = Boolean(thread.data);
  const failed = thread.isError;
  useEffect(() => {
    if (!window.matchMedia(ONE_PANE).matches) return;
    const target = loaded && !failed ? headingRef.current : backRef.current;
    target?.focus({ preventScroll: true });
    target?.scrollIntoView({ block: "start" });
  }, [loaded, failed]);

  const back = (
    <Button
      ref={backRef}
      variant="ghost"
      size="sm"
      className={styles.back}
      onClick={onBack}
    >
      <ArrowLeftIcon aria-hidden />
      All threads
    </Button>
  );

  if (thread.isError) {
    return (
      <>
        {back}
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
      </>
    );
  }
  if (thread.isLoading || !thread.data) {
    return (
      <>
        {back}
        <WorkingState label="Loading thread" />
      </>
    );
  }
  const status = thread.data.status;
  const client = clientName(thread.data.client_id);
  const letters = messages.data
    ? conversationMessages(messages.data, status)
    : [];
  const working =
    draftMutation.isPending ||
    approveMutation.isPending ||
    sendMutation.isPending;

  return (
    <article className={styles.threadDetail} data-testid="board-thread">
      {back}
      <header className={styles.threadHead}>
        <div className="min-w-0">
          <p className={pageStyles.eyebrow}>
            {KIND_LABEL[thread.data.kind]} from {client}
          </p>
          <h2 ref={headingRef} tabIndex={-1} className={styles.threadTitle}>
            {thread.data.subject || KIND_LABEL[thread.data.kind]}
          </h2>
          <p className={styles.threadSub}>
            Opened{" "}
            <time
              dateTime={thread.data.created_at}
              title={fullDate(thread.data.created_at)}
            >
              {formatTimeAgo(thread.data.created_at)}
            </time>
          </p>
        </div>
        <ThreadStatus thread={thread.data} />
      </header>

      {messages.isError ? (
        <ErrorState
          message="Couldn't load messages."
          detail={messages.error.message}
          action={
            <Button
              variant="outline"
              size="sm"
              onClick={() => void messages.refetch()}
            >
              Try again
            </Button>
          }
        />
      ) : messages.isLoading ? (
        <WorkingState label="Loading messages" />
      ) : (
        <section aria-label="Conversation">
          {letters.length === 0 ? (
            <p className={styles.muted}>No messages yet.</p>
          ) : (
            <ol className={styles.letters}>
              {letters.map((message) => (
                <li
                  key={message.id}
                  className={styles.letter}
                  data-author={message.author_kind}
                >
                  <p className={styles.letterHead}>
                    <span className={styles.letterAuthor}>
                      {authorLabel(message.author_kind, client)}
                    </span>
                    <time
                      className={styles.letterTime}
                      dateTime={message.created_at}
                      title={fullDate(message.created_at)}
                    >
                      {formatTimeAgo(message.created_at)}
                    </time>
                  </p>
                  <p className={styles.letterBody}>{message.body}</p>
                </li>
              ))}
            </ol>
          )}
        </section>
      )}

      {canDraft(status) || canApprove(status) || canSendReply(status) ? (
        <div className={cn(pageStyles.pin, working && "pinned")}>
          <section
            aria-label={
              canDraft(status)
                ? "Draft editor"
                : canApprove(status)
                  ? "Approve draft"
                  : "Send reply"
            }
            aria-busy={working}
            className={cn(pageStyles.sheet, styles.draftSheet, "paper-torn")}
            data-testid="board-draft-sheet"
          >
            {canDraft(status) ? (
              <>
                <label htmlFor="board-draft" className={styles.sheetTitle}>
                  Draft a reply
                </label>
                <p className={styles.sheetNote}>
                  Momo holds it here until you approve it. Nothing reaches{" "}
                  {client} before you send.
                </p>
                <Textarea
                  id="board-draft"
                  className={styles.field}
                  value={draftText}
                  onChange={(event) => setDraftText(event.target.value)}
                  placeholder="What should Momo say back?"
                  rows={5}
                />
                {draftMutation.isError ? (
                  <p className={styles.errorText} role="alert">
                    {draftMutation.error.message}
                  </p>
                ) : null}
                <div className={styles.sheetActions}>
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
              </>
            ) : null}

            {canApprove(status) ? (
              <>
                <div className={styles.sheetHead}>
                  <img
                    className={styles.sheetMomo}
                    src="/momentum/momos/lead.svg"
                    alt=""
                    aria-hidden
                    width={44}
                    height={44}
                  />
                  <div className="min-w-0">
                    <h3 className={styles.sheetTitle}>Momo&apos;s draft</h3>
                    <p className={styles.sheetNote}>
                      Waiting on your review. {client} sees nothing until it is
                      approved and sent.
                    </p>
                  </div>
                </div>
                {draft ? (
                  <p className={styles.draftBody}>{draft.body}</p>
                ) : (
                  <p className={styles.muted}>
                    The draft text is not available.
                  </p>
                )}
                {approveMutation.isError ? (
                  <p className={styles.errorText} role="alert">
                    {approveMutation.error.message}
                  </p>
                ) : null}
                <div className={styles.sheetActions}>
                  <Button
                    disabled={approveMutation.isPending}
                    onClick={() => approveMutation.mutate({ threadId })}
                  >
                    {approveMutation.isPending ? "Approving..." : "Approve"}
                  </Button>
                </div>
              </>
            ) : null}

            {canSendReply(status) ? (
              <>
                <div className={styles.sheetHead}>
                  <div className="min-w-0">
                    <label htmlFor="board-reply" className={styles.sheetTitle}>
                      Approved reply
                    </label>
                    <p className={styles.sheetNote}>
                      Ready to send to {client}. Read it once more, then send.
                    </p>
                  </div>
                </div>
                <Textarea
                  id="board-reply"
                  className={styles.field}
                  value={replyText}
                  onChange={(event) => setReplyText(event.target.value)}
                  rows={5}
                />
                {sendMutation.isError ? (
                  <p className={styles.errorText} role="alert">
                    {sendMutation.error.message}
                  </p>
                ) : null}
                <div className={styles.sheetActions}>
                  <Button
                    disabled={!replyText.trim() || sendMutation.isPending}
                    onClick={() =>
                      sendMutation.mutate({ threadId, body: replyText })
                    }
                  >
                    {sendMutation.isPending ? "Sending..." : "Send reply"}
                  </Button>
                </div>
              </>
            ) : null}
          </section>
        </div>
      ) : null}

      {status === "replied" || status === "closed" ? (
        <p className={styles.muted}>
          {status === "replied" ? "Reply sent." : "Thread closed."}
        </p>
      ) : null}
    </article>
  );
}
