"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUp, Plus, RefreshCw, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { SidebarTrigger } from "@/components/ui/sidebar";
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
          `${error.message} Refresh to check the session before retrying. Your next retry uses the same request receipt.`,
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
        setNotice(error.message);
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
        setNotice(error.message);
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
  const error = status.error ?? sessions.error ?? session.error;

  return (
    <section className="momentum-page flex h-full min-h-0 min-w-0 flex-col">
      <header className="border-b px-4 py-5 sm:px-8">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <SidebarTrigger className="-ml-2 md:hidden" />
              <h1 className="text-2xl">OpenAI crew</h1>
            </div>
            <p className="text-muted-foreground mt-1 text-sm">
              MomoBot with GPT-6.1 Sol and up to three OpenAI specialists.
            </p>
          </div>
          <div className="flex gap-2">
            <Button
              variant="outline"
              className="min-h-11"
              aria-label="Refresh agent sessions"
              onClick={refresh}
            >
              <RefreshCw className="size-4" />
            </Button>
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
          </div>
        </div>
      </header>
      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        <aside
          className="max-h-40 shrink-0 overflow-y-auto border-b p-3 lg:max-h-none lg:w-64 lg:border-r lg:border-b-0"
          aria-label="OpenAI sessions"
        >
          {sessions.isLoading && (
            <p className="p-2 text-sm" role="status">
              Loading sessions…
            </p>
          )}
          {sessions.data?.data.length === 0 && (
            <p className="text-muted-foreground p-2 text-sm">
              Your sessions will appear here.
            </p>
          )}
          <ul className="space-y-1">
            {sessions.data?.data.map((item) => (
              <li key={item.id}>
                <button
                  className={`min-h-11 w-full rounded-md px-3 py-2 text-left text-sm ${selected === item.id ? "bg-accent" : "hover:bg-accent/50"}`}
                  aria-current={selected === item.id ? "page" : undefined}
                  onClick={() => {
                    setSelected(item.id);
                    setNotice(null);
                  }}
                >
                  <span className="block truncate">{item.title}</span>
                  <span className="text-muted-foreground text-xs">
                    {item.status.replaceAll("_", " ")}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </aside>
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          <div
            className="min-h-0 flex-1 overflow-y-auto px-4 py-6 sm:px-8"
            aria-label="Agent conversation"
          >
            <div className="mx-auto max-w-3xl space-y-6">
              {!selected && (
                <div className="py-8">
                  <p className="text-xl">Give the crew a task.</p>
                  <p className="text-muted-foreground mt-3 max-w-xl text-sm">
                    OpenAI runs a shared cloud workspace. Return to this session
                    to inspect actual messages, turn results, and generated
                    files.
                  </p>
                </div>
              )}
              {status.isLoading && (
                <p role="status">Checking OpenAI availability…</p>
              )}
              {status.data && !ready && (
                <p className="rounded-md border p-4 text-sm" role="status">
                  {status.data.reason ??
                    "OpenAI is not configured on this server."}
                </p>
              )}
              {error && (
                <p role="alert" className="text-destructive text-sm">
                  {error.message}
                </p>
              )}
              {notice && (
                <p role="alert" className="rounded-md border p-4 text-sm">
                  {notice}
                </p>
              )}
              {data && (
                <div className="flex flex-wrap items-center justify-between gap-2 border-b pb-3">
                  <p className="text-sm" role="status">
                    {data.turn
                      ? `Turn ${data.turn.status.replaceAll("_", " ")}`
                      : `Session ${data.status.replaceAll("_", " ")}`}
                    {data.turn?.output_verified
                      ? " · final output retrieved"
                      : ""}
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
                      {cancel.isPending ? "Cancelling…" : "Stop turn"}
                    </Button>
                  )}
                </div>
              )}
              {data?.last_error && (
                <p role="alert" className="text-destructive text-sm">
                  {data.last_error}
                </p>
              )}
              {data && visibleItems.length === 0 && (
                <p className="text-muted-foreground text-sm">
                  No text output has been verified yet.
                </p>
              )}
              {visibleItems.map((item) => (
                <article key={item.id} className="min-w-0 border-b pb-5">
                  <p className="text-muted-foreground mb-2 text-xs">
                    {item.type === "create_subagent_call"
                      ? "Delegation"
                      : item.type === "agent_message"
                        ? "Specialist message"
                        : (item.role ?? item.type)}
                    {item.subagent_id
                      ? ` · Specialist ${item.subagent_id}`
                      : ""}
                    {item.phase ? ` · ${item.phase.replaceAll("_", " ")}` : ""}
                    {item.sender_agent_id && item.recipient_agent_id
                      ? ` · ${item.sender_agent_id} to ${item.recipient_agent_id}`
                      : ""}
                  </p>
                  <p className="text-sm leading-7 [overflow-wrap:anywhere] break-words whitespace-pre-wrap">
                    {item.text}
                  </p>
                </article>
              ))}
              {data?.operation_pending && (
                <p role="status" className="text-sm">
                  Checking whether OpenAI received the previous action. A new
                  task stays paused until its outcome is known.
                </p>
              )}
              {data?.history_truncated && (
                <p className="text-muted-foreground text-xs">
                  This view has reached its history limit. Older items may be
                  unavailable here.
                </p>
              )}
              {!!data?.artifacts.length && (
                <div>
                  <h2 className="mb-2 text-sm">Generated files</h2>
                  <ul>
                    {data.artifacts.map((artifact) => (
                      <li key={artifact.id}>
                        <button
                          className="inline-flex min-h-11 max-w-full items-center text-left text-sm break-all underline"
                          disabled={download.isPending || !ready}
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
                          {artifact.path}
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {!!data?.required_actions.length && (
                <p role="status" className="text-sm">
                  This session requires an action that this app cannot approve
                  yet. Stop the turn before starting another task.
                </p>
              )}
              {data?.usage && (
                <p className="text-muted-foreground text-xs">
                  Input tokens: {data.usage.input_tokens ?? "unavailable"} ·
                  Output tokens: {data.usage.output_tokens ?? "unavailable"}
                </p>
              )}
            </div>
          </div>
          <form
            className="shrink-0 border-t px-4 pt-4 pb-[max(1rem,env(safe-area-inset-bottom))] sm:px-8"
            onSubmit={(event) => {
              event.preventDefault();
              const input = draft.trim();
              if (!owner || !scope || !mayCreate || !input || busy || !ready)
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
              <label htmlFor="openai-task" className="mb-2 block text-sm">
                Task for the crew
              </label>
              <div className="flex items-end gap-2">
                <textarea
                  id="openai-task"
                  rows={3}
                  maxLength={16000}
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                  placeholder="Research, create a draft, or solve a problem…"
                  className="bg-background focus-visible:ring-ring min-h-24 min-w-0 flex-1 resize-y rounded-md border p-3 text-base focus-visible:ring-2 focus-visible:outline-none"
                  disabled={send.isPending || !scope}
                />
                <Button
                  type="submit"
                  className="min-h-11 min-w-11"
                  disabled={!ready || !mayCreate || busy || !draft.trim()}
                  aria-label="Send task"
                >
                  <ArrowUp className="size-4" />
                </Button>
              </div>
              <p className="text-muted-foreground mt-2 text-xs">
                Cloud execution uses your OpenAI API account. Browser sign-in
                and actions on connected accounts are unavailable in this
                release.
              </p>
            </div>
          </form>
        </div>
      </div>
    </section>
  );
}
