"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { useAuth } from "@/core/auth/AuthProvider";
import { hasPermission, PERMISSIONS } from "@/core/auth/permissions";
import { handOffResearchDownload } from "@/core/browserbase/api";
import { isStaticWebsiteOnly } from "@/core/static-mode";
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

import { JevboxPreparationPane } from "./jevbox-preparation-panel";
import { WorkflowForm } from "./workflow-form";
import { WorkflowRunDetail } from "./workflow-run";

function explanation(error: Error): string {
  const messages: Record<string, string> = {
    queue_full:
      "The workflow queue is full. Wait for a slot before trying again.",
    daily_model_budget_exhausted:
      "The daily model-call budget has been reached.",
    framework_unavailable: "This execution framework is currently unavailable.",
    not_enabled: "Workflow execution is disabled.",
    input_invalid: "Check the required fields and their allowed bounds.",
    uncertain_provider_attempt:
      "The provider outcome is unconfirmed. This run is held until it can be reconciled.",
    run_not_interrupted:
      "This run is no longer interrupted. Refresh its saved state.",
  };
  return messages[error.message] ?? error.message;
}

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
  return (
    <div className="min-w-0 space-y-6 p-4 md:p-6">
      <div className="space-y-2 text-sm">
        <p>
          Your runs: {status.running} running · {status.queued} queued · shared
          limit {status.limits.max_running} running at once
        </p>
        <p className="text-muted-foreground">
          Queue capacity {status.limits.max_queued}. A workflow definition
          starts work only when you run it.
        </p>
        <details className="rounded-md border p-3">
          <summary className="min-h-11 cursor-pointer py-2">
            Framework availability
          </summary>
          <ul className="space-y-2">
            {FRAMEWORKS.filter((name) => status.frameworks[name]).map(
              (name) => (
                <li key={name} className="break-words">
                  {FRAMEWORK_LABELS[name]}:{" "}
                  {status.frameworks[name]?.available
                    ? "available"
                    : "unavailable"}
                  {status.frameworks[name]?.detail
                    ? ` · ${status.frameworks[name]?.detail}`
                    : ""}
                </li>
              ),
            )}
          </ul>
        </details>
      </div>
      {notice && (
        <p role="status" className="rounded-md border p-3 text-sm break-words">
          {notice}
        </p>
      )}
      {submission && !create.isPending && (
        <Button
          variant="outline"
          className="min-h-11"
          disabled={!mayCreate || !status.enabled}
          onClick={() => create.mutate(submission)}
        >
          Retry same request
        </Button>
      )}
      <div className="grid min-w-0 gap-6 lg:grid-cols-[minmax(260px,340px)_minmax(0,1fr)]">
        <section aria-label="Workflow catalog" className="min-w-0 space-y-3">
          <h2 className="text-xl">Workflow catalog</h2>
          <label htmlFor="workflow-search" className="block text-sm">
            Search workflows
          </label>
          <input
            id="workflow-search"
            type="search"
            maxLength={200}
            className="border-input bg-background focus-visible:ring-ring min-h-11 w-full min-w-0 rounded-md border px-3 text-sm focus-visible:ring-2 focus-visible:outline-none"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
          <label htmlFor="workflow-category" className="block text-sm">
            Workflow category
          </label>
          <select
            id="workflow-category"
            className="border-input bg-background focus-visible:ring-ring min-h-11 w-full min-w-0 rounded-md border px-3 text-sm focus-visible:ring-2 focus-visible:outline-none"
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
          {catalog.isLoading && (
            <p role="status">Loading workflow definitions…</p>
          )}
          {catalog.error && <p role="alert">{explanation(catalog.error)}</p>}
          {catalog.data && (
            <p role="status" className="text-muted-foreground text-sm">
              {filtered.length} of {catalog.data.total} workflow definitions
            </p>
          )}
          <ul className="max-h-96 overflow-y-auto rounded-md border lg:max-h-[44rem]">
            {filtered.map((entry) => (
              <li key={entry.id} className="border-b last:border-b-0">
                <button
                  type="button"
                  aria-pressed={workflowId === entry.id}
                  disabled={locked}
                  onClick={() => setWorkflowId(entry.id)}
                  className={cn(
                    "hover:bg-muted focus-visible:ring-ring min-h-11 w-full p-3 text-left focus-visible:ring-2 focus-visible:outline-none focus-visible:ring-inset disabled:opacity-60",
                    workflowId === entry.id && "bg-muted",
                  )}
                >
                  <span className="block text-sm break-words">
                    {entry.title}
                  </span>
                  <span className="text-muted-foreground mt-1 block text-xs break-words">
                    {entry.category} · {entry.summary}
                  </span>
                </button>
              </li>
            ))}
          </ul>
          {catalog.data && !filtered.length && (
            <p className="text-sm">No workflows match these filters.</p>
          )}
        </section>
        <div className="min-w-0 space-y-6">
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
            <p className="rounded-md border p-4 text-sm">
              Choose a workflow to review its inputs and acceptance checks.
            </p>
          )}
          {run.isLoading && runId && (
            <p role="status">Loading saved workflow run…</p>
          )}
          {run.error && <p role="alert">{explanation(run.error)}</p>}
          {data && (
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
          )}
        </div>
      </div>
      <section
        aria-label="Saved workflow runs"
        className="space-y-3 border-t pt-5"
      >
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-xl">Saved runs</h2>
          <Button variant="outline" className="min-h-11" onClick={refresh}>
            <RefreshCw className="size-4" /> Refresh saved runs
          </Button>
        </div>
        {runs.error && <p role="alert">{explanation(runs.error)}</p>}
        {runs.isLoading && <p role="status">Loading saved runs…</p>}
        {runs.data && !runs.data.runs.length && (
          <p className="text-muted-foreground text-sm">
            No saved workflow runs in this workspace.
          </p>
        )}
        <ul className="divide-y rounded-md border">
          {runs.data?.runs.map((entry) => (
            <li key={entry.id}>
              <button
                type="button"
                className={cn(
                  "hover:bg-muted focus-visible:ring-ring min-h-11 w-full px-3 py-3 text-left text-sm focus-visible:ring-2 focus-visible:outline-none focus-visible:ring-inset",
                  entry.id === runId && "bg-muted",
                )}
                onClick={() => setRunId(entry.id)}
                aria-pressed={entry.id === runId}
              >
                <span className="block break-words">{entry.title}</span>
                <span className="text-muted-foreground block text-xs">
                  {entry.status} ·{" "}
                  {FRAMEWORK_LABELS[entry.framework] ?? entry.framework}
                  {entry.accepted && entry.status === "completed"
                    ? " · accepted"
                    : ""}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </section>
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
  function refreshStatus() {
    void queryClient.invalidateQueries({
      queryKey: ["workflows", owner, "status"],
    });
  }
  return (
    <main className="momentum-page flex h-full min-h-0 min-w-0 flex-col overflow-x-hidden motion-reduce:[&_*]:animate-none motion-reduce:[&_*]:transition-none">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b p-4 md:px-6">
        <div className="flex min-w-0 items-center gap-3">
          <SidebarTrigger className="min-h-11 min-w-11" />
          <div>
            <h1 className="text-2xl">Workflow room</h1>
            <p className="text-muted-foreground text-sm">
              Agency and personal workflows.
            </p>
          </div>
        </div>
        <Button
          variant="outline"
          className="min-h-11 min-w-11"
          onClick={refreshStatus}
          disabled={!connected}
          aria-label="Refresh workflow room"
        >
          <RefreshCw className="size-4" />
        </Button>
      </header>
      <div className="min-w-0 flex-1 overflow-y-auto overscroll-contain">
        {!connected && (
          <p className="p-4 text-sm">
            Workflows require the connected app and authenticated workflow read
            access.
          </p>
        )}
        {connected && owner && <JevboxPreparationPane owner={owner} />}
        {status.isLoading && connected && (
          <p role="status" className="p-4">
            Loading workflow capabilities…
          </p>
        )}
        {status.error && (
          <p role="alert" className="p-4">
            {explanation(status.error)}
          </p>
        )}
        {scope && scope === invalidScope && (
          <p role="alert" className="p-4">
            The workspace changed. Refresh the workflow room to read its current
            scope.
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
    </main>
  );
}
