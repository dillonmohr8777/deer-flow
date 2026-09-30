"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
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
import { handOffResearchDownload } from "@/core/browserbase/api";
import { isStaticWebsiteOnly } from "@/core/static-mode";
import { toDateTimeAttr } from "@/core/utils/datetime";
import {
  createWorkflowRun,
  downloadWorkflowArtifact,
  getWorkflowCatalog,
  getWorkflowRun,
  getWorkflowStatus,
  isAdmissionUnconfirmed,
  isWorkflowScopeError,
  listWorkflowRuns,
  updateWorkflowRun,
} from "@/core/workflows/api";
import {
  FRAMEWORK_LABELS,
  FRAMEWORKS,
  isWorkflowActive,
  type WorkflowInput,
  type WorkflowRun,
  type WorkflowStatus,
} from "@/core/workflows/types";
import { cn } from "@/lib/utils";

import { WorkflowForm } from "./workflow-form";
import { WorkflowRunDetail } from "./workflow-run";
import { explanation, runState, runTime } from "./workflow-words";

function ScopedWorkflowRoom({
  owner,
  scope,
  status,
  onScopeChanged,
  onRefreshStatus,
}: {
  owner: string;
  scope: string;
  status: WorkflowStatus;
  onScopeChanged: () => void;
  onRefreshStatus: () => void;
}) {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const mounted = useRef(true);
  const controllers = useRef(new Set<AbortController>());
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");
  const [workflowId, setWorkflowId] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [submission, setSubmission] = useState<{
    input: WorkflowInput;
    key: string;
  } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const detailRef = useRef<HTMLDivElement>(null);
  const mayCreate = hasPermission(user, PERMISSIONS.RUNS_CREATE);
  const mayCancel = hasPermission(user, PERMISSIONS.RUNS_CANCEL);
  const prefix = ["workflows", owner, scope];
  useEffect(() => {
    mounted.current = true;
    const active = controllers.current;
    return () => {
      mounted.current = false;
      for (const controller of active) controller.abort();
      void queryClient.cancelQueries({ queryKey: ["workflows", owner, scope] });
      queryClient.removeQueries({ queryKey: ["workflows", owner, scope] });
    };
  }, [owner, scope, queryClient]);
  async function guarded<T>(
    operation: (signal: AbortSignal) => Promise<T>,
  ): Promise<T> {
    const controller = new AbortController();
    controllers.current.add(controller);
    try {
      return await operation(controller.signal);
    } finally {
      controllers.current.delete(controller);
    }
  }
  const catalog = useQuery({
    queryKey: [...prefix, "catalog"],
    queryFn: ({ signal }) => getWorkflowCatalog(scope, signal),
    retry: false,
  });
  const runs = useQuery({
    queryKey: [...prefix, "runs"],
    queryFn: ({ signal }) => listWorkflowRuns(scope, signal),
    retry: false,
    refetchInterval: (query) =>
      query.state.data?.runs.some((run) => isWorkflowActive(run.status))
        ? 4000
        : false,
  });
  const run = useQuery({
    queryKey: [...prefix, "runs", runId],
    queryFn: ({ signal }) => getWorkflowRun(runId!, scope, signal),
    enabled: !!runId,
    retry: false,
    refetchInterval: (query) =>
      isWorkflowActive(query.state.data?.status ?? "") ? 2500 : false,
  });
  useEffect(() => {
    if ([catalog.error, runs.error, run.error].some(isWorkflowScopeError))
      onScopeChanged();
  }, [catalog.error, runs.error, run.error, onScopeChanged]);
  // A chosen or just-started run opens under the list; bring it into view,
  // instantly under reduced motion, as Scheduled tasks does for its sheet.
  useEffect(() => {
    if (!runId) return;
    const reduce = window.matchMedia?.(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    detailRef.current?.scrollIntoView?.({
      block: "nearest",
      behavior: reduce ? "auto" : "smooth",
    });
  }, [runId]);
  function refresh() {
    void queryClient.invalidateQueries({
      queryKey: ["workflows", owner, scope],
    });
    onRefreshStatus();
  }
  function store(data: WorkflowRun) {
    setRunId(data.id);
    queryClient.setQueryData([...prefix, "runs", data.id], data);
    refresh();
  }
  const create = useMutation({
    mutationFn: (request: { input: WorkflowInput; key: string }) =>
      guarded((signal) =>
        createWorkflowRun(request.input, request.key, scope, signal),
      ),
    retry: false,
    onSuccess: (data) => {
      if (!mounted.current) return;
      setSubmission(null);
      setNotice(null);
      store(data);
    },
    onError: (error) => {
      if (!mounted.current) return;
      if (isWorkflowScopeError(error)) {
        onScopeChanged();
        return;
      }
      if (!isAdmissionUnconfirmed(error)) setSubmission(null);
      setNotice(
        `${explanation(error)}${isAdmissionUnconfirmed(error) ? " The request is unconfirmed. Retry uses the same saved request; review saved runs first." : ""}`,
      );
      refresh();
    },
  });
  const action = useMutation({
    mutationFn: (input: { id: string; action: "cancel" | "resume" }) =>
      guarded((signal) =>
        updateWorkflowRun(input.id, input.action, scope, signal),
      ),
    retry: false,
    onSuccess: (data) => {
      if (mounted.current) {
        setNotice(null);
        store(data);
      }
    },
    onError: (error) => {
      if (!mounted.current) return;
      if (isWorkflowScopeError(error)) onScopeChanged();
      else {
        setNotice(explanation(error));
        refresh();
      }
    },
  });
  const download = useMutation({
    mutationFn: (data: WorkflowRun) =>
      guarded((signal) =>
        downloadWorkflowArtifact(data.id, scope, data.artifact!, signal),
      ),
    retry: false,
    onSuccess: (blob, data) => {
      if (!mounted.current) return;
      handOffResearchDownload(
        blob,
        `workflow-${data.id.replace(/[^a-zA-Z0-9_-]/g, "_")}.json`,
      );
      setNotice(
        "Artifact size and SHA-256 matched the saved receipt. The file was handed to your browser; confirm it in Downloads.",
      );
    },
    onError: (error) => {
      if (!mounted.current) return;
      if (isWorkflowScopeError(error)) onScopeChanged();
      else setNotice(explanation(error));
    },
  });
  const definitions = catalog.data?.workflows ?? [];
  const categories = [
    ...new Set(definitions.map((definition) => definition.category)),
  ].sort();
  const needle = search.trim().toLocaleLowerCase();
  const filtered = definitions.filter(
    (definition) =>
      (!category || definition.category === category) &&
      (!needle ||
        `${definition.title} ${definition.category} ${definition.summary} ${definition.id}`
          .toLocaleLowerCase()
          .includes(needle)),
  );
  const definition = definitions.find(
    (definition) => definition.id === workflowId,
  );
  const data = run.error ? undefined : run.data;
  const locked = !!submission || create.isPending || action.isPending;
  const savedRuns = runs.data?.runs ?? [];
  return (
    <div className="flex min-w-0 flex-col gap-10">
      <section aria-labelledby="workflow-runs-title" className="min-w-0">
        <h2 id="workflow-runs-title" className="text-xl">
          Your runs
        </h2>
        <p className="text-muted-foreground mt-1 text-sm">
          {status.running} running, {status.queued} queued. Up to{" "}
          {status.limits.max_running} can run at once across the workspace, and{" "}
          {status.limits.max_queued} more can wait.
        </p>
        <details className="mt-1 text-sm">
          <summary className="text-muted-foreground hover:text-foreground inline-flex min-h-11 cursor-pointer items-center underline decoration-1 underline-offset-4">
            Which frameworks can run
          </summary>
          <ul className="mt-1 mb-2 space-y-1">
            {FRAMEWORKS.filter((name) => status.frameworks[name]).map(
              (name) => (
                <li key={name} className="break-words">
                  <StatusTag
                    tone={status.frameworks[name]?.available ? "ok" : "idle"}
                  >
                    {FRAMEWORK_LABELS[name]}:{" "}
                    {status.frameworks[name]?.available
                      ? "available"
                      : "unavailable"}
                  </StatusTag>
                  {status.frameworks[name]?.detail ? (
                    <span className="text-muted-foreground">
                      {" "}
                      · {status.frameworks[name]?.detail}
                    </span>
                  ) : null}
                </li>
              ),
            )}
          </ul>
        </details>
        {notice && (
          <p
            role="status"
            className={cn(pageStyles.sheet, "mt-3 p-3 text-sm break-words")}
          >
            {notice}
          </p>
        )}
        {submission && !create.isPending && (
          <Button
            variant="outline"
            className="mt-3 min-h-11"
            disabled={!mayCreate || !status.enabled}
            onClick={() => create.mutate(submission)}
          >
            Retry same request
          </Button>
        )}
        <div className="mt-3">
          {runs.isLoading && <WorkingState label="Loading your runs" />}
          {runs.error && (
            <ErrorState
              message="Your runs could not be loaded."
              detail={explanation(runs.error)}
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
          {runs.data && !savedRuns.length && (
            <EmptyState
              momo="builder"
              title="No runs yet"
              action={
                <Button asChild variant="outline" className="min-h-11">
                  <a href="#workflow-catalog">Choose a workflow</a>
                </Button>
              }
            >
              Workflows you run from the catalog show up here with their
              receipts, newest first.
            </EmptyState>
          )}
          {savedRuns.length > 0 && (
            <ul
              aria-label="Saved workflow runs"
              className={cn(
                "divide-y border-y",
                pageStyles.rows,
                pageStyles.slips,
              )}
            >
              {savedRuns.map((entry) => {
                const state = runState(entry);
                const selected = entry.id === runId;
                return (
                  <li
                    key={entry.id}
                    className={cn(
                      pageStyles.pin,
                      entry.status === "running" && "pinned",
                    )}
                  >
                    <button
                      type="button"
                      className={cn(
                        "focus-visible:ring-ring flex min-h-11 w-full flex-col gap-1 px-3 py-3 text-left text-sm transition-colors focus-visible:ring-2 focus-visible:outline-none focus-visible:ring-inset",
                        selected
                          ? "bg-card shadow-[inset_0_0_0_1px_var(--primary)] forced-colors:outline-2 forced-colors:-outline-offset-2 forced-colors:outline-[color:Highlight] forced-colors:outline-solid"
                          : "hover:bg-accent",
                      )}
                      onClick={() => setRunId(entry.id)}
                      aria-pressed={selected}
                    >
                      <span className="flex items-start justify-between gap-3">
                        <span className="min-w-0 font-bold [overflow-wrap:anywhere]">
                          {entry.title}
                        </span>
                        <StatusTag
                          tone={state.tone}
                          className="mt-0.5 shrink-0"
                        >
                          {state.label}
                        </StatusTag>
                      </span>
                      <span className="text-muted-foreground">
                        <time
                          dateTime={toDateTimeAttr(entry.created_at)}
                          title={new Date(entry.created_at).toLocaleString()}
                        >
                          {runTime(entry.created_at)}
                        </time>
                        {" · "}
                        {FRAMEWORK_LABELS[entry.framework] ?? entry.framework}
                      </span>
                      {entry.status === "failed" && entry.error ? (
                        <span className="text-destructive line-clamp-2 [overflow-wrap:anywhere]">
                          {explanation(new Error(entry.error))}
                        </span>
                      ) : null}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
        <div ref={detailRef} className="scroll-mt-4">
          {run.isLoading && runId && (
            <WorkingState label="Loading the saved run" className="mt-4" />
          )}
          {run.error && (
            <ErrorState
              className="mt-4"
              message="This run could not be loaded."
              detail={explanation(run.error)}
            />
          )}
          {data && (
            <div className="mt-4">
              <WorkflowRunDetail
                run={data}
                busy={action.isPending || download.isPending}
                mayCancel={mayCancel}
                mayResume={
                  mayCreate &&
                  status.enabled &&
                  !!status.frameworks[data.framework]?.available
                }
                onAction={(operation) =>
                  action.mutate({ id: data.id, action: operation })
                }
                onDownload={() => download.mutate(data)}
              />
            </div>
          )}
        </div>
      </section>
      <div className="grid min-w-0 gap-6 lg:grid-cols-[minmax(260px,340px)_minmax(0,1fr)]">
        <section
          id="workflow-catalog"
          aria-labelledby="workflow-catalog-title"
          className="min-w-0 scroll-mt-4 space-y-3"
        >
          <h2 id="workflow-catalog-title" className="text-xl">
            Workflow catalog
          </h2>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-1">
            <div className="min-w-0 space-y-1">
              <label
                htmlFor="workflow-search"
                className="block text-sm font-semibold"
              >
                Search workflows
              </label>
              <input
                id="workflow-search"
                type="search"
                maxLength={200}
                className="border-input bg-card focus-visible:ring-ring min-h-11 w-full min-w-0 rounded-md border px-3 text-sm focus-visible:ring-2 focus-visible:outline-none"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
            </div>
            <div className="min-w-0 space-y-1">
              <label
                htmlFor="workflow-category"
                className="block text-sm font-semibold"
              >
                Workflow category
              </label>
              <select
                id="workflow-category"
                className="border-input bg-card focus-visible:ring-ring min-h-11 w-full min-w-0 rounded-md border px-3 text-sm focus-visible:ring-2 focus-visible:outline-none"
                value={category}
                onChange={(event) => setCategory(event.target.value)}
              >
                <option value="">All categories</option>
                {categories.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </div>
          </div>
          {catalog.isLoading && (
            <WorkingState label="Loading workflow definitions" />
          )}
          {catalog.error && (
            <ErrorState
              message="The catalog could not be loaded."
              detail={explanation(catalog.error)}
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
          {catalog.data && (
            <p role="status" className="text-muted-foreground text-sm">
              {filtered.length} of {catalog.data.total} workflow definitions
            </p>
          )}
          {filtered.length > 0 && (
            <ul
              className={cn(
                "max-h-96 divide-y overflow-y-auto border-y lg:max-h-[44rem]",
                pageStyles.rows,
                "max-sm:max-h-none max-sm:overflow-visible",
                pageStyles.slips,
              )}
            >
              {filtered.map((entry) => (
                <li key={entry.id}>
                  <button
                    type="button"
                    aria-pressed={workflowId === entry.id}
                    disabled={locked}
                    onClick={() => setWorkflowId(entry.id)}
                    className={cn(
                      "focus-visible:ring-ring min-h-11 w-full p-3 text-left transition-colors focus-visible:ring-2 focus-visible:outline-none focus-visible:ring-inset disabled:opacity-60",
                      workflowId === entry.id
                        ? "bg-card shadow-[inset_0_0_0_1px_var(--primary)] forced-colors:outline-2 forced-colors:-outline-offset-2 forced-colors:outline-[color:Highlight] forced-colors:outline-solid"
                        : "hover:bg-accent",
                    )}
                  >
                    <span className="block text-sm font-bold break-words">
                      {entry.title}
                    </span>
                    <span className="text-muted-foreground mt-1 block text-sm break-words">
                      {entry.category} · {entry.summary}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          {catalog.data && !filtered.length && (
            <p className="text-sm">No workflows match these filters.</p>
          )}
        </section>
        <div className="min-w-0">
          {definition ? (
            <WorkflowForm
              key={definition.id}
              definition={definition}
              status={status}
              locked={locked}
              mayCreate={mayCreate}
              onRun={(input) => {
                if (
                  locked ||
                  !mayCreate ||
                  !status.enabled ||
                  !status.frameworks[input.framework]?.available
                )
                  return;
                const request = { input, key: crypto.randomUUID() };
                setSubmission(request);
                setNotice(null);
                create.mutate(request);
              }}
            />
          ) : (
            <p
              className={cn(
                pageStyles.sheet,
                "text-muted-foreground p-4 text-sm max-lg:hidden",
              )}
            >
              Choose a workflow to review its inputs and acceptance checks.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

export function WorkflowRoom() {
  const { user } = useAuth();
  const owner = user?.id;
  const queryClient = useQueryClient();
  const [invalidScope, setInvalidScope] = useState<string | null>(null);
  const connected =
    !!owner && !isStaticWebsiteOnly() && hasPermission(user, "runs:read");
  const status = useQuery({
    queryKey: ["workflows", owner, "status"],
    queryFn: ({ signal }) => getWorkflowStatus(owner!, signal),
    enabled: connected,
    retry: false,
    refetchInterval: connected ? 10000 : false,
  });
  const scope = status.error ? undefined : status.data?.owner_scope;
  const trusted = connected && !!scope && scope !== invalidScope;
  useEffect(() => setInvalidScope(null), [owner]);
  // One refresh for the whole room: status, catalog, runs and the open run.
  function refreshStatus() {
    void queryClient.invalidateQueries({ queryKey: ["workflows", owner] });
  }
  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody className={pageStyles.page}>
        {/* The page scrolls inside the body, like Desk and Scheduled tasks,
            so the header and the phone tab bar keep their edges. */}
        <ScrollArea className="size-full">
          <div className="momentum-page mx-auto flex w-full max-w-(--container-width-lg) min-w-0 flex-col gap-6 p-4 pb-28 sm:p-6 sm:pb-28 motion-reduce:[&_*]:animate-none motion-reduce:[&_*]:transition-none">
            <header className="flex items-end justify-between gap-3 pt-2">
              <div className="min-w-0">
                <h1 className="text-2xl">Workflows</h1>
                <p className={cn(pageStyles.lede, "mt-1")}>
                  Agency routines with set inputs and acceptance checks. Nothing
                  starts until you run one.
                </p>
              </div>
              <Button
                variant="outline"
                size="icon"
                className="size-11 shrink-0"
                onClick={refreshStatus}
                disabled={!connected}
                aria-label="Refresh workflow room"
                title="Refresh"
              >
                <RefreshCw className="size-4" />
              </Button>
            </header>
            {!connected && (
              <p className={cn(pageStyles.sheet, "p-4 text-sm")}>
                Workflows require the connected app and authenticated workflow
                read access.
              </p>
            )}
            {status.isLoading && connected && (
              <WorkingState label="Loading workflows" />
            )}
            {status.error && (
              <ErrorState
                message="Workflows could not be loaded."
                detail={explanation(status.error)}
                action={
                  <Button
                    variant="outline"
                    className="min-h-11"
                    disabled={status.isFetching}
                    onClick={refreshStatus}
                  >
                    Try again
                  </Button>
                }
              />
            )}
            {scope && scope === invalidScope && (
              <p role="alert" className={cn(pageStyles.sheet, "p-4 text-sm")}>
                The workspace changed. Refresh the workflow room to read its
                current scope.
              </p>
            )}
            {trusted && status.data && (
              <ScopedWorkflowRoom
                key={`${owner}:${scope}`}
                owner={owner}
                scope={scope}
                status={status.data}
                onRefreshStatus={refreshStatus}
                onScopeChanged={() => {
                  setInvalidScope(scope);
                  refreshStatus();
                }}
              />
            )}
          </div>
        </ScrollArea>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}
