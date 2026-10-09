"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, ExternalLink, RefreshCw, Square } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { useAuth } from "@/core/auth/AuthProvider";
import { hasPermission, PERMISSIONS } from "@/core/auth/permissions";
import {
  cancelBrowserResearch,
  createBrowserResearch,
  getBrowserbaseStatus,
  getBrowserResearch,
  handOffResearchDownload,
  isBrowserResearchBusy,
  listBrowserResearch,
  loadBrowserResearchScreenshot,
  type BrowserResearchInput,
} from "@/core/browserbase/api";
import { parseResearchUrls, publicResearchUrl } from "@/core/browserbase/urls";
import { cn } from "@/lib/utils";

interface Submission {
  owner: string;
  scope: string;
  input: BrowserResearchInput;
  key: string;
}

function CapturedScreenshot({
  owner,
  scope,
  runId,
  index,
  title,
}: {
  owner: string;
  scope: string;
  runId: string;
  index: number;
  title: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const screenshot = useQuery({
    queryKey: ["browserbase", owner, scope, "screenshot", runId, index],
    queryFn: ({ signal }) =>
      loadBrowserResearchScreenshot(runId, index, scope, signal),
    enabled: expanded,
    retry: false,
    staleTime: Infinity,
  });
  useEffect(() => {
    if (!screenshot.data) return;
    const objectUrl = URL.createObjectURL(screenshot.data);
    setImageUrl(objectUrl);
    return () => URL.revokeObjectURL(objectUrl);
  }, [screenshot.data]);

  return (
    <div className="space-y-3">
      <Button
        variant="outline"
        className="min-h-11"
        onClick={() => setExpanded((value) => !value)}
        aria-expanded={expanded}
      >
        {expanded ? "Hide screenshot" : "View screenshot"}
      </Button>
      {expanded && (
        <div className="space-y-3">
          {screenshot.isLoading && (
            <p role="status" className="text-sm">
              Loading captured screenshot…
            </p>
          )}
          {screenshot.error && (
            <p role="alert" className="text-destructive text-sm">
              {screenshot.error.message}
            </p>
          )}
          {imageUrl && screenshot.data && (
            <>
              {/* The image is an authenticated Blob; Next image optimization cannot retrieve it. */}
              <img
                src={imageUrl}
                alt={`Browserbase rendering of the captured public text: ${title}`}
                className="h-auto max-w-full rounded-md border"
              />
              <Button
                variant="outline"
                className="min-h-11"
                onClick={() =>
                  handOffResearchDownload(
                    screenshot.data,
                    `browser-research-${runId}-page-${index + 1}.png`,
                  )
                }
              >
                <Download className="size-4" /> Download screenshot
              </Button>
            </>
          )}
        </div>
      )}
    </div>
  );
}

export function BrowserResearchWorkspace() {
  const { user } = useAuth();
  const owner = user?.id;
  const mayCreate = !!owner && hasPermission(user, PERMISSIONS.RUNS_CREATE);
  const mayCancel = !!owner && hasPermission(user, PERMISSIONS.RUNS_CANCEL);
  const currentOwner = useRef(owner);
  currentOwner.current = owner;
  const currentScope = useRef<string | undefined>(undefined);
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<string | undefined>();
  const [title, setTitle] = useState("");
  const [urls, setUrls] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [submission, setSubmission] = useState<Submission | null>(null);

  const status = useQuery({
    queryKey: ["browserbase", owner, "status"],
    queryFn: ({ signal }) => getBrowserbaseStatus(owner!, signal),
    enabled: !!owner,
    retry: false,
  });
  const scope = status.data?.owner_scope;
  currentScope.current = scope;
  useEffect(() => {
    setSelected(undefined);
    setTitle("");
    setUrls("");
    setNotice(null);
    setSubmission(null);
  }, [owner, scope]);
  const runs = useQuery({
    queryKey: ["browserbase", owner, scope, "research"],
    queryFn: ({ signal }) => listBrowserResearch(scope!, signal),
    enabled: !!owner && !!scope && !status.error,
    retry: false,
    refetchInterval: (query) =>
      query.state.data?.data.some((run) => isBrowserResearchBusy(run.status)) &&
      query.state.dataUpdateCount < 72
        ? 2500
        : false,
  });
  const run = useQuery({
    queryKey: ["browserbase", owner, scope, "research", selected],
    queryFn: ({ signal }) => getBrowserResearch(selected!, scope!, signal),
    enabled: !!owner && !!scope && !!selected && !status.error,
    retry: false,
    refetchInterval: (query) =>
      isBrowserResearchBusy(query.state.data?.status ?? "") &&
      query.state.dataUpdateCount < 72
        ? 2500
        : false,
  });
  useEffect(() => {
    if (
      [runs.error, run.error].some(
        (error) => error?.message === "workspace_scope_changed",
      )
    )
      void queryClient.invalidateQueries({
        queryKey: ["browserbase", owner, "status"],
      });
  }, [runs.error, run.error, queryClient, owner]);
  const refresh = () =>
    void queryClient.invalidateQueries({ queryKey: ["browserbase", owner] });
  const create = useMutation({
    mutationFn: (request: Submission) =>
      createBrowserResearch(request.input, request.key, request.scope),
    retry: false,
    onSuccess: (data, request) => {
      if (
        currentOwner.current !== request.owner ||
        currentScope.current !== request.scope
      )
        return;
      setSelected(data.id);
      setSubmission(null);
      setUrls("");
      setTitle("");
      setNotice(null);
      queryClient.setQueryData(
        ["browserbase", request.owner, request.scope, "research", data.id],
        data,
      );
      void queryClient.invalidateQueries({
        queryKey: ["browserbase", request.owner, request.scope, "research"],
      });
      void queryClient.invalidateQueries({
        queryKey: ["browserbase", request.owner, "status"],
      });
    },
    onError: (error, request) => {
      if (
        currentOwner.current !== request.owner ||
        currentScope.current !== request.scope
      )
        return;
      setNotice(
        `${error.message} The request is unconfirmed. Retry uses the same receipt; check saved captures before continuing.`,
      );
      refresh();
    },
  });
  const cancel = useMutation({
    mutationFn: (request: { id: string; owner: string; scope: string }) =>
      cancelBrowserResearch(request.id, request.scope),
    retry: false,
    onSuccess: (data, request) => {
      if (
        currentOwner.current !== request.owner ||
        currentScope.current !== request.scope
      )
        return;
      queryClient.setQueryData(
        ["browserbase", request.owner, request.scope, "research", data.id],
        data,
      );
      refresh();
    },
    onError: (error, request) => {
      if (
        currentOwner.current === request.owner &&
        currentScope.current === request.scope
      )
        setNotice(error.message);
    },
  });
  const download = useMutation({
    mutationFn: (request: { id: string; owner: string; scope: string }) =>
      getBrowserResearch(request.id, request.scope),
    retry: false,
    onSuccess: (data, request) => {
      if (
        currentOwner.current !== request.owner ||
        currentScope.current !== request.scope
      )
        return;
      handOffResearchDownload(
        new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }),
        `browser-research-${data.id}.json`,
      );
      setNotice(
        "Captured evidence was handed to your browser for download. Confirm the saved file in Downloads.",
      );
    },
    onError: (error, request) => {
      if (
        currentOwner.current === request.owner &&
        currentScope.current === request.scope
      )
        setNotice(error.message);
    },
  });

  const data = run.data;
  const active =
    (runs.data?.data.some((item) => isBrowserResearchBusy(item.status)) ??
      false) ||
    isBrowserResearchBusy(data?.status ?? "");
  const ready = status.data?.available === true && !!scope && !status.error;
  const error = status.error ?? runs.error ?? run.error;
  const limits = status.data?.limits;
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!owner || !scope || !mayCreate || !ready || create.isPending) return;
    if (submission?.owner === owner && submission.scope === scope) {
      create.mutate(submission);
      return;
    }
    if (active || !runs.data || runs.error) return;
    try {
      const request: Submission = {
        owner,
        scope,
        input: {
          urls: parseResearchUrls(urls, limits?.max_pages ?? 3),
          ...(title.trim() ? { title: title.trim() } : {}),
        },
        key: crypto.randomUUID(),
      };
      setSubmission(request);
      setNotice(null);
      create.mutate(request);
    } catch (error) {
      setNotice(
        error instanceof Error ? error.message : "Check the page URLs.",
      );
    }
  }

  return (
    <section className="momentum-page flex h-full min-h-0 min-w-0 flex-col">
      <header className="shrink-0 border-b px-4 py-5 sm:px-8">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <SidebarTrigger className="-ml-2 min-h-11 min-w-11 md:hidden" />
              <h1 className="text-2xl">Browser research</h1>
            </div>
            <p className="text-muted-foreground mt-1 text-sm">
              Capture public page evidence with Browserbase.
            </p>
          </div>
          <Button
            variant="outline"
            className="min-h-11 min-w-11"
            aria-label="Refresh saved captures"
            onClick={refresh}
          >
            <RefreshCw className="size-4" />
          </Button>
        </div>
      </header>
      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        <aside
          className="max-h-40 shrink-0 overflow-y-auto border-b p-3 lg:max-h-none lg:w-64 lg:border-r lg:border-b-0"
          aria-label="Saved browser captures"
        >
          {runs.isLoading && (
            <p role="status" className="p-2 text-sm">
              Loading saved captures…
            </p>
          )}
          {runs.data?.data.length === 0 && (
            <p className="text-muted-foreground p-2 text-sm">
              Your saved captures will appear here.
            </p>
          )}
          <ul className="space-y-1">
            {runs.data?.data.map((item) => (
              <li key={item.id}>
                <button
                  className={cn(
                    "hover:bg-accent/50 min-h-11 w-full rounded-md px-3 py-2 text-left text-sm",
                    selected === item.id && "bg-accent",
                  )}
                  aria-current={selected === item.id ? "page" : undefined}
                  onClick={() => {
                    setSelected(item.id);
                    setNotice(null);
                  }}
                >
                  <span className="block truncate">{item.title}</span>
                  <span className="text-muted-foreground text-xs">
                    {item.status}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </aside>
        <main className="min-h-0 min-w-0 flex-1 overflow-y-auto px-4 py-6 pb-[max(1.5rem,env(safe-area-inset-bottom))] sm:px-8">
          <div className="mx-auto max-w-3xl space-y-6">
            <form
              onSubmit={submit}
              className="space-y-4 rounded-lg border p-4 sm:p-5"
            >
              <h2 className="text-lg">Capture public sources</h2>
              <p className="text-muted-foreground text-sm">
                Up to {limits?.max_pages ?? 3} HTTPS pages in one{" "}
                {limits?.session_timeout_seconds ?? 180} second session. Public
                read-only snapshots preserve extracted text and a Browserbase
                rendering. Remote page scripts, browsing actions, and sign-in
                are disabled.
              </p>
              <div className="space-y-2">
                <label htmlFor="research-title" className="text-sm">
                  Capture title (optional)
                </label>
                <input
                  id="research-title"
                  maxLength={120}
                  value={title}
                  disabled={!!submission || !scope}
                  onChange={(event) => setTitle(event.target.value)}
                  className="bg-background min-h-11 w-full rounded-md border px-3 text-sm"
                  placeholder="Tonight’s official docs"
                />
              </div>
              <div className="space-y-2">
                <label htmlFor="research-urls" className="text-sm">
                  Public HTTPS URLs, one per line
                </label>
                <textarea
                  id="research-urls"
                  rows={3}
                  maxLength={8192}
                  value={urls}
                  disabled={!!submission || !scope}
                  onChange={(event) => setUrls(event.target.value)}
                  className="bg-background min-h-24 w-full resize-y rounded-md border p-3 text-sm"
                  placeholder="https://developers.openai.com/api/docs"
                  aria-describedby="research-url-note"
                />
                <p
                  id="research-url-note"
                  className="text-muted-foreground text-xs"
                >
                  The server verifies public destinations before capture. Keep
                  private links and credentials out of this form.
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-3">
                <Button
                  type="submit"
                  className="min-h-11"
                  disabled={
                    !mayCreate ||
                    !ready ||
                    create.isPending ||
                    (!submission &&
                      (active || !runs.data || !!runs.error || !urls.trim()))
                  }
                >
                  {create.isPending
                    ? "Checking capture…"
                    : submission
                      ? "Retry same request"
                      : "Capture pages"}
                </Button>
                {!mayCreate && owner && (
                  <p className="text-muted-foreground text-sm">
                    You have read-only access.
                  </p>
                )}
                {active && (
                  <p role="status" className="text-muted-foreground text-sm">
                    A capture is already queued or running.
                  </p>
                )}
              </div>
            </form>
            {status.isLoading && (
              <p role="status">Checking Browserbase availability…</p>
            )}
            {status.data && !ready && (
              <p className="rounded-md border p-4 text-sm" role="status">
                {status.data.reason ??
                  "Browserbase is unavailable on this server."}
              </p>
            )}
            {status.data && (
              <p className="text-muted-foreground text-sm">
                {status.data.remaining_minutes === null
                  ? "Remaining browser minutes unavailable."
                  : `${status.data.remaining_minutes} browser minutes remaining.`}
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
            {run.isLoading && selected && (
              <p role="status">Retrieving saved capture…</p>
            )}
            {data && (
              <section aria-label="Capture evidence" className="space-y-5">
                <div className="flex flex-wrap items-start justify-between gap-3 border-b pb-4">
                  <div className="min-w-0">
                    <h2 className="text-xl break-words">{data.title}</h2>
                    <p
                      role="status"
                      className="text-muted-foreground mt-2 text-sm"
                    >
                      Capture {data.status}
                      {data.status === "completed" && data.pages.length
                        ? " · captured evidence retrieved"
                        : ""}
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {isBrowserResearchBusy(data.status) && (
                      <Button
                        variant="outline"
                        className="min-h-11"
                        disabled={!mayCancel || cancel.isPending}
                        onClick={() =>
                          owner &&
                          scope &&
                          cancel.mutate({ id: data.id, owner, scope })
                        }
                      >
                        <Square className="size-3" />
                        {cancel.isPending ? "Stopping…" : "Stop capture"}
                      </Button>
                    )}
                    <Button
                      variant="outline"
                      className="min-h-11"
                      disabled={!data.pages.length || download.isPending}
                      onClick={() =>
                        owner &&
                        scope &&
                        download.mutate({ id: data.id, owner, scope })
                      }
                    >
                      <Download className="size-4" />
                      Download evidence
                    </Button>
                  </div>
                </div>
                {data.last_error && (
                  <p role="alert" className="text-destructive text-sm">
                    {data.last_error}
                  </p>
                )}
                {data.pages.length === 0 && (
                  <p className="text-muted-foreground text-sm">
                    No page evidence has been retrieved.
                  </p>
                )}
                {data.pages.map((page) => {
                  const source = publicResearchUrl(page.final_url || page.url);
                  return (
                    <article
                      key={page.index}
                      className="space-y-4 rounded-lg border p-4 sm:p-5"
                    >
                      <div className="space-y-2">
                        <h3 className="text-lg break-words">
                          {page.title || "Untitled captured page"}
                        </h3>
                        {source ? (
                          <a
                            href={source}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex min-h-11 max-w-full items-center gap-2 text-sm break-all underline"
                          >
                            <span className="min-w-0">{source}</span>
                            <ExternalLink className="size-4 shrink-0" />
                          </a>
                        ) : (
                          <p className="text-sm break-all">
                            Source URL unavailable.
                          </p>
                        )}
                        <p className="text-muted-foreground text-xs">
                          Public read-only snapshot
                        </p>
                      </div>
                      <details>
                        <summary className="min-h-11 cursor-pointer py-3 text-sm">
                          Read captured text
                        </summary>
                        <pre className="bg-muted max-h-96 overflow-y-auto rounded-md p-3 font-sans text-sm break-words whitespace-pre-wrap">
                          {page.text || "No extracted text was returned."}
                        </pre>
                      </details>
                      {owner && scope && page.screenshot_url && (
                        <CapturedScreenshot
                          key={`${owner}:${scope}:${data.id}:${page.index}`}
                          owner={owner}
                          scope={scope}
                          runId={data.id}
                          index={page.index}
                          title={page.title || "Untitled captured page"}
                        />
                      )}
                    </article>
                  );
                })}
                <p className="text-muted-foreground text-sm">
                  {data.usage.browser_minutes === null
                    ? "Run browser minutes unavailable."
                    : `Run usage: ${data.usage.browser_minutes} browser minutes.`}{" "}
                  Cost unavailable.{" "}
                  {data.session_closed === true
                    ? "Cloud session closed."
                    : data.session_closed === false
                      ? "Cloud session remains open."
                      : "Cloud session closure unconfirmed."}
                </p>
              </section>
            )}
          </div>
        </main>
      </div>
    </section>
  );
}
