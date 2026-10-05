"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  ArrowUp,
  Download,
  Plus,
  RefreshCw,
  Square,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  EmptyState,
  ErrorState,
  pageStyles,
  StatusTag,
  WorkingState,
} from "@/components/workspace/page-body";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useAuth } from "@/core/auth/AuthProvider";
import { hasPermission, PERMISSIONS } from "@/core/auth/permissions";
import {
  cancelAgentTurn,
  downloadAgentArtifact,
  getAgentSession,
  getOpenAIAgentStatus,
  handOffAgentDownload,
  isAgentBusy,
  listAgentSessions,
  submitAgentInput,
} from "@/core/openai-agents/api";
import { toDateTimeAttr } from "@/core/utils/datetime";
import { cn } from "@/lib/utils";

import {
  CREW_GENERIC,
  crewAuthor,
  crewState,
  crewWords,
  crewWorking,
  specialistNumbers,
} from "./openai-crew-words";
import { runTime } from "./workflows/workflow-words";

export function OpenAIAgentRoom() {
  const { user } = useAuth();
  const owner = user?.id;
  const mayCreate = !!owner && hasPermission(user, PERMISSIONS.RUNS_CREATE);
  const mayCancel = !!owner && hasPermission(user, PERMISSIONS.RUNS_CANCEL);
  const currentOwner = useRef(owner);
  currentOwner.current = owner;
  const currentScope = useRef<string | undefined>(undefined);
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<string | undefined>();
  const [draft, setDraft] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const sessionHeading = useRef<HTMLHeadingElement>(null);
  const revealSession = useRef(false);
  const submission = useRef<{
    owner: string;
    scope: string;
    input: string;
    session?: string;
    key: string;
  } | null>(null);
  const status = useQuery({
    queryKey: ["openai-agents", owner, "status"],
    queryFn: ({ signal }) => getOpenAIAgentStatus(owner!, signal),
    enabled: !!owner,
    retry: false,
  });
  const scope = status.data?.owner_scope;
  currentScope.current = scope;
  useEffect(() => {
    setSelected(undefined);
    setDraft("");
    setNotice(null);
    submission.current = null;
  }, [owner, scope]);
  const sessions = useQuery({
    queryKey: ["openai-agents", owner, scope, "sessions"],
    queryFn: ({ signal }) => listAgentSessions(scope!, signal),
    enabled: !!owner && !!scope && !status.error,
    retry: false,
    refetchInterval: (query) =>
      query.state.data?.data.some((item) => isAgentBusy(item.status)) &&
      query.state.dataUpdateCount < 48
        ? 2500
        : false,
  });
  const session = useQuery({
    queryKey: ["openai-agents", owner, scope, "session", selected],
    queryFn: ({ signal }) => getAgentSession(selected!, scope!, signal),
    enabled: !!owner && !!scope && !!selected && !status.error,
    retry: false,
    refetchInterval: (query) =>
      (isAgentBusy(query.state.data?.status ?? "") ||
        query.state.data?.operation_pending) &&
      query.state.dataUpdateCount < 48
        ? 2500
        : false,
  });
  useEffect(() => {
    if (
      [sessions.error, session.error].some(
        (error) => error?.message === "workspace_scope_changed",
      )
    )
      void queryClient.invalidateQueries({
        queryKey: ["openai-agents", owner, "status"],
      });
  }, [sessions.error, session.error, queryClient, owner]);
  const refresh = () =>
    void queryClient.invalidateQueries({ queryKey: ["openai-agents", owner] });
  const send = useMutation({
    mutationFn: (request: NonNullable<typeof submission.current>) =>
      submitAgentInput(
        request.input,
        request.key,
        request.scope,
        request.session,
      ),
    retry: false,
    onSuccess: (data, request) => {
      if (
        currentOwner.current !== request.owner ||
        currentScope.current !== request.scope
      )
        return;
      setSelected(data.id);
      setDraft("");
      submission.current = null;
      queryClient.setQueryData(
        ["openai-agents", request.owner, request.scope, "session", data.id],
        data,
      );
      void queryClient.invalidateQueries({
        queryKey: ["openai-agents", request.owner, request.scope, "sessions"],
      });
      setNotice(null);
    },
    onError: (error, request) => {
      if (
        currentOwner.current === request.owner &&
        currentScope.current === request.scope
      ) {
        setNotice(
          `${crewWords(error)} Your next try reuses the same request receipt, so it cannot run twice.`,
        );
        refresh();
      }
    },
  });
  const cancel = useMutation({
    mutationFn: (request: { id: string; owner: string; scope: string }) =>
      cancelAgentTurn(request.id, request.scope),
    retry: false,
    onSuccess: (data, request) => {
      if (
        currentOwner.current !== request.owner ||
        currentScope.current !== request.scope
      )
        return;
      queryClient.setQueryData(
        ["openai-agents", request.owner, request.scope, "session", data.id],
        data,
      );
      refresh();
    },
    onError: (error, request) => {
      if (
        currentOwner.current === request.owner &&
        currentScope.current === request.scope
      ) {
        setNotice(crewWords(error));
        refresh();
      }
    },
  });
  const download = useMutation({
    mutationFn: (request: {
      owner: string;
      scope: string;
      sessionId: string;
      artifactId: string;
      path: string;
    }) =>
      downloadAgentArtifact(
        request.sessionId,
        request.artifactId,
        request.scope,
      ),
    retry: false,
    onSuccess: (blob, request) => {
      if (
        currentOwner.current !== request.owner ||
        currentScope.current !== request.scope
      )
        return;
      handOffAgentDownload(blob, request.path);
      setNotice(
        "File handed to your browser for download. Confirm the saved file in Downloads.",
      );
    },
    onError: (error, request) => {
      if (
        currentOwner.current === request.owner &&
        currentScope.current === request.scope
      ) {
        setNotice(crewWords(error));
        refresh();
      }
    },
  });

  const data = session.data;
  const busy =
    isAgentBusy(data?.status ?? "") ||
    data?.operation_pending === true ||
    send.isPending;
  const ready = status.data?.available === true && !!scope && !status.error;
  const visibleItems = data?.items.filter((item) => item.text) ?? [];
  const numbers = specialistNumbers(visibleItems);
  const error = status.error ?? sessions.error ?? session.error;
  // An unavailable crew offers no task field: nothing it could send would run.
  const unavailable = !!status.error || (!!status.data && !ready);
  const reason =
    status.data && !ready
      ? crewWords(status.data.reason ?? "openai_agents_unavailable")
      : null;
  const state = data ? crewState(data.turn?.status ?? data.status) : null;
  const saved = sessions.data?.data ?? [];
  const openedId = data?.id;
  useEffect(() => {
    // A tapped session takes focus at its title, so on a phone, where the
    // list steps aside, the reader lands on what they opened.
    if (!revealSession.current || openedId !== selected) return;
    revealSession.current = false;
    sessionHeading.current?.focus({ preventScroll: false });
  }, [openedId, selected]);

  const open = (id: string) => {
    setSelected(id);
    setNotice(null);
    revealSession.current = true;
  };
  const back = () => {
    const id = selected;
    setSelected(undefined);
    setNotice(null);
    // Return focus to the slip the session was opened from.
    requestAnimationFrame(() =>
      document
        .querySelector<HTMLButtonElement>(
          `[data-crew-session="${CSS.escape(id ?? "")}"]`,
        )
        ?.focus(),
    );
  };

  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody className={pageStyles.page}>
        {/* Wide screens keep the session list and the conversation side by
            side, each scrolling on its own. Phones show one pane at a time
            and scroll it as one, with the task field held at the bottom. */}
        <div className="momentum-page flex size-full min-h-0 min-w-0 flex-col max-lg:overflow-y-auto motion-reduce:[&_*]:animate-none motion-reduce:[&_*]:transition-none">
          <header
            className={cn(
              "flex flex-wrap items-end justify-between gap-3 px-4 pt-6 pb-4 sm:px-8 lg:border-b",
              selected && "max-lg:hidden",
            )}
          >
            <div className="min-w-0">
              <h1>OpenAI crew</h1>
              <p className={cn(pageStyles.lede, "mt-1")}>
                MomoBot leads up to {status.data?.max_concurrent_subagents ?? 3}{" "}
                OpenAI specialists in a shared cloud workspace.
              </p>
            </div>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="icon"
                className="size-11 shrink-0"
                aria-label="Refresh agent sessions"
                title="Refresh"
                onClick={refresh}
              >
                <RefreshCw className="size-4" />
              </Button>
              {!unavailable && (
                <Button
                  variant="outline"
                  className="min-h-11"
                  onClick={() => {
                    setSelected(undefined);
                    setDraft("");
                    setNotice(null);
                    submission.current = null;
                  }}
                  disabled={send.isPending}
                >
                  <Plus className="size-4" />
                  New session
                </Button>
              )}
            </div>
          </header>
          <div className="flex min-w-0 flex-1 flex-col lg:min-h-0 lg:flex-row">
            {/* With no sessions yet the column would hold one line; the empty
                state beside it says where they will appear instead. */}
            {!status.error && !(sessions.data && saved.length === 0) && (
              <aside
                className={cn(
                  "shrink-0 px-4 pb-2 sm:px-8 lg:w-72 lg:overflow-y-auto lg:border-r lg:px-4 lg:py-4",
                  selected && "max-lg:hidden",
                )}
                aria-labelledby="crew-sessions-title"
              >
                <h2
                  id="crew-sessions-title"
                  className={cn(pageStyles.eyebrow, "mb-2")}
                >
                  Your sessions
                </h2>
                {sessions.isLoading && (
                  <WorkingState label="Loading sessions" />
                )}
                {saved.length > 0 && (
                  <ul
                    className={cn(
                      pageStyles.rows,
                      pageStyles.slips,
                      "divide-y border-y",
                    )}
                  >
                    {saved.map((item) => {
                      const itemState = crewState(item.status);
                      const chosen = selected === item.id;
                      return (
                        <li
                          key={item.id}
                          className={cn(
                            pageStyles.pin,
                            crewWorking(item.status) && "pinned",
                          )}
                        >
                          <button
                            type="button"
                            data-crew-session={item.id}
                            className={cn(
                              "focus-visible:ring-ring flex min-h-11 w-full flex-col gap-1 px-3 py-3 text-left text-sm transition-colors focus-visible:ring-2 focus-visible:outline-none focus-visible:ring-inset",
                              chosen
                                ? "bg-card shadow-[inset_0_0_0_1px_var(--primary)] forced-colors:outline-2 forced-colors:-outline-offset-2 forced-colors:outline-[color:Highlight] forced-colors:outline-solid"
                                : "hover:bg-accent",
                            )}
                            aria-current={chosen ? "page" : undefined}
                            title={item.title}
                            onClick={() => open(item.id)}
                          >
                            <span className="line-clamp-2 font-bold [overflow-wrap:anywhere]">
                              {item.title}
                            </span>
                            <span className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
                              <StatusTag tone={itemState.tone}>
                                {itemState.label}
                              </StatusTag>
                              <time
                                className="text-muted-foreground"
                                dateTime={toDateTimeAttr(item.updated_at)}
                                title={new Date(
                                  item.updated_at,
                                ).toLocaleString()}
                              >
                                {runTime(item.updated_at)}
                              </time>
                            </span>
                            {item.last_error && (
                              <span className="text-destructive line-clamp-2 [overflow-wrap:anywhere]">
                                {crewWords(item.last_error)}
                              </span>
                            )}
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </aside>
            )}
            <div className="flex min-w-0 flex-1 flex-col lg:min-h-0">
              <div
                className="flex-1 px-4 py-6 sm:px-8 lg:min-h-0 lg:overflow-y-auto"
                aria-label="Agent conversation"
              >
                <div className="mx-auto max-w-3xl space-y-6">
                  {selected && (
                    <Button
                      variant="ghost"
                      className="-ml-3 min-h-11 lg:hidden"
                      onClick={back}
                    >
                      <ArrowLeft className="size-4" />
                      All sessions
                    </Button>
                  )}
                  {status.isLoading && (
                    <WorkingState label="Checking the OpenAI crew" />
                  )}
                  {error && (
                    <ErrorState
                      message={
                        status.error
                          ? "The OpenAI crew could not be checked."
                          : sessions.error
                            ? "Your sessions could not be loaded."
                            : "This session could not be opened."
                      }
                      detail={
                        crewWords(error) === CREW_GENERIC
                          ? undefined
                          : crewWords(error)
                      }
                      action={
                        <Button
                          variant="outline"
                          className="min-h-11"
                          onClick={refresh}
                        >
                          Try again
                        </Button>
                      }
                    />
                  )}
                  {reason && (
                    <p
                      role="status"
                      className={cn(pageStyles.sheet, "p-4 text-sm")}
                    >
                      {reason}
                    </p>
                  )}
                  {!selected && !unavailable && !status.isLoading && (
                    <EmptyState momo="lead" title="Give the crew a task">
                      {saved.length
                        ? "Describe the job below, or open a session to see its messages, results and files."
                        : "Describe the job below. Your sessions will appear here, each with its messages, results and files."}
                    </EmptyState>
                  )}
                  {selected && session.isLoading && (
                    <WorkingState label="Opening the session" />
                  )}
                  {notice && (
                    <p
                      role="alert"
                      className={cn(pageStyles.sheet, "p-4 text-sm")}
                    >
                      {notice}
                    </p>
                  )}
                  {data && state && (
                    <header className="space-y-2 border-b pb-4">
                      <h2
                        ref={sessionHeading}
                        tabIndex={-1}
                        className="text-xl [overflow-wrap:anywhere] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
                      >
                        {data.title}
                      </h2>
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <p
                          className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm"
                          role="status"
                        >
                          <StatusTag tone={state.tone}>{state.label}</StatusTag>
                          {data.turn?.output_verified && (
                            <span>Final answer retrieved</span>
                          )}
                          <time
                            className="text-muted-foreground"
                            dateTime={toDateTimeAttr(data.created_at)}
                            title={new Date(data.created_at).toLocaleString()}
                          >
                            Started {runTime(data.created_at)}
                          </time>
                        </p>
                        {isAgentBusy(data.status) && (
                          <Button
                            variant="outline"
                            className="min-h-11"
                            disabled={cancel.isPending || !mayCancel}
                            onClick={() =>
                              owner &&
                              scope &&
                              cancel.mutate({ id: data.id, owner, scope })
                            }
                          >
                            <Square className="size-3" />
                            {cancel.isPending ? "Stopping…" : "Stop turn"}
                          </Button>
                        )}
                      </div>
                    </header>
                  )}
                  {data?.last_error && (
                    <p role="alert" className="text-destructive text-sm">
                      {crewWords(data.last_error)}
                    </p>
                  )}
                  {data && visibleItems.length === 0 && (
                    <p className="text-muted-foreground text-sm">
                      No text output has been verified yet.
                    </p>
                  )}
                  {visibleItems.map((item) => {
                    const mine =
                      item.role === "user" && item.type === "message";
                    return (
                      <article
                        key={item.id}
                        className={cn(
                          "min-w-0",
                          mine && "bg-secondary rounded-[2px_5px_3px_6px] p-4",
                        )}
                      >
                        <p className="mb-1 text-sm font-semibold">
                          {crewAuthor(item, numbers)}
                        </p>
                        <p className="text-sm leading-6 [overflow-wrap:anywhere] break-words whitespace-pre-wrap">
                          {item.text}
                        </p>
                      </article>
                    );
                  })}
                  {data?.operation_pending && (
                    <WorkingState label="Checking whether OpenAI received the previous action. A new task stays paused until its outcome is known." />
                  )}
                  {data?.history_truncated && (
                    <p className="text-muted-foreground text-sm">
                      This view has reached its history limit. Older items may
                      be unavailable here.
                    </p>
                  )}
                  {!!data?.artifacts.length && (
                    <section aria-labelledby="crew-files-title">
                      <h3
                        id="crew-files-title"
                        className={cn(pageStyles.eyebrow, "mb-2")}
                      >
                        Generated files
                      </h3>
                      <ul className={cn(pageStyles.rows, "divide-y border-y")}>
                        {data.artifacts.map((artifact) => (
                          <li key={artifact.id}>
                            <button
                              type="button"
                              className="hover:bg-accent focus-visible:ring-ring inline-flex min-h-11 w-full items-center gap-2 px-2 text-left font-mono text-sm break-all focus-visible:ring-2 focus-visible:outline-none focus-visible:ring-inset"
                              disabled={download.isPending || !ready}
                              aria-label={`Download ${artifact.path}`}
                              onClick={() =>
                                owner &&
                                scope &&
                                download.mutate({
                                  owner,
                                  scope,
                                  sessionId: data.id,
                                  artifactId: artifact.id,
                                  path: artifact.path,
                                })
                              }
                            >
                              <Download
                                className="size-4 shrink-0"
                                aria-hidden="true"
                              />
                              {artifact.path}
                            </button>
                          </li>
                        ))}
                      </ul>
                    </section>
                  )}
                  {!!data?.required_actions.length && (
                    <p role="status" className="text-sm">
                      This session requires an action that this app cannot
                      approve yet. Stop the turn before starting another task.
                    </p>
                  )}
                  {data?.usage && (
                    <p className="text-muted-foreground text-sm">
                      Tokens: {tokens(data.usage.input_tokens)} in,{" "}
                      {tokens(data.usage.output_tokens)} out
                    </p>
                  )}
                </div>
              </div>
              {!unavailable && (
                <form
                  className="bg-background shrink-0 border-t px-4 pt-4 pb-[max(1rem,env(safe-area-inset-bottom))] max-lg:sticky max-lg:bottom-0 sm:px-8"
                  onSubmit={(event) => {
                    event.preventDefault();
                    const input = draft.trim();
                    if (
                      !owner ||
                      !scope ||
                      !mayCreate ||
                      !input ||
                      busy ||
                      !ready
                    )
                      return;
                    const previous = submission.current;
                    const request =
                      previous?.owner === owner &&
                      previous.scope === scope &&
                      previous.input === input &&
                      previous.session === selected
                        ? previous
                        : {
                            owner,
                            scope,
                            input,
                            session: selected,
                            key: crypto.randomUUID(),
                          };
                    submission.current = request;
                    send.mutate(request);
                  }}
                >
                  <div className="mx-auto max-w-3xl">
                    <label
                      htmlFor="openai-task"
                      className="mb-2 block text-sm font-semibold"
                    >
                      Task for the crew
                    </label>
                    <div className="flex items-end gap-2">
                      <textarea
                        id="openai-task"
                        rows={selected ? 2 : 3}
                        maxLength={16000}
                        value={draft}
                        onChange={(event) => setDraft(event.target.value)}
                        placeholder={
                          selected
                            ? "Reply, or give the next step"
                            : "Describe the job and what done looks like"
                        }
                        className="bg-card placeholder:text-muted-foreground focus-visible:ring-ring min-h-16 min-w-0 flex-1 resize-y rounded-md border p-3 text-base focus-visible:ring-2 focus-visible:outline-none sm:text-sm"
                        disabled={send.isPending || !scope}
                      />
                      <Button
                        type="submit"
                        size="icon"
                        className="size-11 shrink-0"
                        disabled={!ready || !mayCreate || busy || !draft.trim()}
                        aria-label="Send task"
                      >
                        <ArrowUp className="size-4" />
                      </Button>
                    </div>
                    <p className="text-muted-foreground mt-2 text-xs">
                      Runs on your OpenAI API account. Browser sign-in and
                      actions on connected accounts are not available yet.
                    </p>
                  </div>
                </form>
              )}
            </div>
          </div>
        </div>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}

function tokens(value: number | null): string {
  return value === null ? "not recorded" : value.toLocaleString();
}
