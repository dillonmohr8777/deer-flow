"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, ExternalLink, RefreshCw, Square } from "lucide-react";
import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type RefObject,
} from "react";

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
import {
  cancelBrowserResearch,
  createBrowserResearch,
  getBrowserbaseStatus,
  getBrowserResearch,
  handOffResearchDownload,
  isBrowserResearchBusy,
  listBrowserResearch,
  loadBrowserResearchScreenshot,
  type BrowserResearch,
  type BrowserResearchInput,
} from "@/core/browserbase/api";
import { parseResearchUrls, publicResearchUrl } from "@/core/browserbase/urls";
import { toDateTimeAttr } from "@/core/utils/datetime";
import { cn } from "@/lib/utils";

import { browserWords, captureState } from "./browser-research-words";
import { runTime } from "./workflows/workflow-words";

const CONTROL =
  "border-input bg-background placeholder:text-muted-foreground focus-visible:ring-ring min-h-11 w-full min-w-0 rounded-md border px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 disabled:opacity-60 max-sm:text-base";

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
              {browserWords(screenshot.error)}
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
  // Create and URL errors belong to the form; stop and download notices
  // belong to the receipt, so each reason shows beside what it is about.
  const [formNotice, setFormNotice] = useState<string | null>(null);
  // Tied to the capture it is about, so switching captures never shows
  // one capture's notice on another.
  const [receiptNotice, setReceiptNotice] = useState<{
    id: string;
    text: string;
  } | null>(null);
  const [submission, setSubmission] = useState<Submission | null>(null);
  const receiptRef = useRef<HTMLDivElement>(null);
  const receiptHeading = useRef<HTMLHeadingElement>(null);
  // A chosen capture opens under the list; once it has loaded, bring it into
  // view (instantly under reduced motion) and hand it focus, as Scheduled
  // tasks does for its sheet, so a tap never changes something off screen.
  // The id of the capture to reveal once it has loaded.
  const bringReceipt = useRef<string | null>(null);

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
    setFormNotice(null);
    setReceiptNotice(null);
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
      setFormNotice(null);
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
      setFormNotice(
        `${browserWords(error)} The request is unconfirmed. Retry uses the same receipt; check saved captures before continuing.`,
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
        setReceiptNotice({ id: request.id, text: browserWords(error) });
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
      setReceiptNotice({
        id: request.id,
        text: "Captured evidence was handed to your browser for download. Confirm the saved file in Downloads.",
      });
    },
    onError: (error, request) => {
      if (
        currentOwner.current === request.owner &&
        currentScope.current === request.scope
      )
        setReceiptNotice({ id: request.id, text: browserWords(error) });
    },
  });

  const data = run.data;
  function revealReceipt() {
    const reduce = window.matchMedia?.(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    receiptRef.current?.scrollIntoView?.({
      block: "start",
      behavior: reduce ? "auto" : "smooth",
    });
    receiptHeading.current?.focus({ preventScroll: true });
  }
  // Only the load the tap asked for reveals the receipt; a later poll never
  // moves focus, so typing in the form is never interrupted.
  useEffect(() => {
    if (bringReceipt.current !== data?.id) return;
    bringReceipt.current = null;
    revealReceipt();
  }, [data]);
  // A failed read or a selection the tap did not make drops the pending
  // reveal, so a later refetch never pulls focus out of the form.
  useEffect(() => {
    if (run.error || bringReceipt.current !== selected)
      bringReceipt.current = null;
  }, [run.error, selected]);
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
      setFormNotice(null);
      create.mutate(request);
    } catch (error) {
      setFormNotice(
        error instanceof Error ? browserWords(error) : "Check the page URLs.",
      );
    }
  }

  const saved = runs.data?.data ?? [];
  const reason =
    status.data && !ready
      ? browserWords(status.data.reason ?? "provider_unavailable")
      : null;
  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody className={pageStyles.page}>
        {/* The page scrolls inside the body, like Workflows and Desk, so the
            header and the phone tab bar keep their edges. */}
        <ScrollArea className="size-full">
          <div className="momentum-page mx-auto flex w-full max-w-(--container-width-lg) min-w-0 flex-col gap-8 p-4 pb-28 sm:p-6 sm:pb-28 motion-reduce:[&_*]:animate-none motion-reduce:[&_*]:transition-none">
            <header className="flex items-end justify-between gap-3 pt-2">
              <div className="min-w-0">
                <h1 className="text-2xl">Browser research</h1>
                <p className={cn(pageStyles.lede, "mt-1")}>
                  Save public pages as evidence: their text and a rendering,
                  read only.
                </p>
                {status.data && (
                  <p className="text-muted-foreground mt-1 text-sm">
                    {status.data.remaining_minutes === null
                      ? "Remaining browser minutes unavailable."
                      : `${status.data.remaining_minutes} browser minutes remaining.`}
                  </p>
                )}
              </div>
              <Button
                variant="outline"
                size="icon"
                className="size-11 shrink-0"
                aria-label="Refresh saved captures"
                title="Refresh"
                onClick={refresh}
              >
                <RefreshCw className="size-4" />
              </Button>
            </header>
            {status.isLoading && <WorkingState label="Checking Browserbase" />}
            {error && (
              <ErrorState
                message="Browser research could not be loaded."
                detail={browserWords(error)}
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
              <p role="status" className={cn(pageStyles.sheet, "p-4 text-sm")}>
                {reason}
              </p>
            )}
            {!status.error && (
              <section aria-labelledby="captures-title" className="min-w-0">
                <h2 id="captures-title" className="text-xl">
                  Your captures
                </h2>
                <div className="mt-3">
                  {runs.isLoading && (
                    <WorkingState label="Loading saved captures" />
                  )}
                  {runs.data && !saved.length && (
                    <EmptyState
                      momo="research"
                      title="No captures yet"
                      action={
                        <Button asChild variant="outline" className="min-h-11">
                          <a href="#capture-form">Capture a page</a>
                        </Button>
                      }
                    >
                      Pages you capture are saved here with their text and a
                      rendering, newest first.
                    </EmptyState>
                  )}
                  {saved.length > 0 && (
                    <ul
                      aria-label="Saved browser captures"
                      className={cn(
                        pageStyles.rows,
                        pageStyles.slips,
                        "divide-y border-y",
                      )}
                    >
                      {saved.map((item) => {
                        const state = captureState(item.status);
                        const chosen = selected === item.id;
                        return (
                          <li
                            key={item.id}
                            className={cn(
                              pageStyles.pin,
                              item.status === "running" && "pinned",
                            )}
                          >
                            <button
                              type="button"
                              className={cn(
                                "focus-visible:ring-ring flex min-h-11 w-full flex-col gap-1 px-3 py-3 text-left text-sm transition-colors focus-visible:ring-2 focus-visible:outline-none focus-visible:ring-inset",
                                chosen
                                  ? "bg-card shadow-[inset_0_0_0_1px_var(--primary)] forced-colors:outline-2 forced-colors:-outline-offset-2 forced-colors:outline-[color:Highlight] forced-colors:outline-solid"
                                  : "hover:bg-accent",
                              )}
                              aria-pressed={chosen}
                              onClick={() => {
                                setReceiptNotice(null);
                                if (data?.id === item.id) {
                                  // Already open: reveal it now rather than
                                  // on some later poll.
                                  bringReceipt.current = null;
                                  revealReceipt();
                                  return;
                                }
                                bringReceipt.current = item.id;
                                setSelected(item.id);
                              }}
                            >
                              <span className="flex items-start justify-between gap-3">
                                <span className="line-clamp-2 min-w-0 font-bold [overflow-wrap:anywhere]">
                                  {item.title}
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
                                  dateTime={toDateTimeAttr(item.created_at)}
                                  title={new Date(
                                    item.created_at,
                                  ).toLocaleString()}
                                >
                                  {runTime(item.created_at)}
                                </time>
                              </span>
                              {item.status === "failed" && (
                                <span className="text-destructive line-clamp-2 [overflow-wrap:anywhere]">
                                  {browserWords(item.last_error)}
                                </span>
                              )}
                            </button>
                          </li>
                        );
                      })}
                    </ul>
                  )}
                </div>
                <div ref={receiptRef} className="scroll-mt-4">
                  {run.isLoading && selected && (
                    <WorkingState
                      label="Retrieving saved capture"
                      className="mt-4"
                    />
                  )}
                  {data && (
                    <CaptureReceipt
                      data={data}
                      owner={owner}
                      scope={scope}
                      headingRef={receiptHeading}
                      notice={
                        receiptNotice?.id === data.id
                          ? receiptNotice.text
                          : null
                      }
                      mayCancel={mayCancel}
                      stopping={cancel.isPending}
                      downloading={download.isPending}
                      onStop={() =>
                        owner &&
                        scope &&
                        cancel.mutate({ id: data.id, owner, scope })
                      }
                      onDownload={() =>
                        owner &&
                        scope &&
                        download.mutate({ id: data.id, owner, scope })
                      }
                    />
                  )}
                </div>
              </section>
            )}
            {!status.error && (
              <form
                id="capture-form"
                onSubmit={submit}
                aria-labelledby="capture-form-title"
                className={cn(
                  pageStyles.sheet,
                  "max-w-3xl min-w-0 scroll-mt-4 space-y-4 p-4 sm:p-5",
                )}
              >
                <div className="space-y-1.5">
                  <h2 id="capture-form-title" className="text-xl">
                    Capture public pages
                  </h2>
                  <p className="text-sm leading-relaxed">
                    Up to {limits?.max_pages ?? 3} https pages in one{" "}
                    {limits?.session_timeout_seconds ?? 180} second session. The
                    capture only reads: page scripts, clicks and sign in are
                    off.
                  </p>
                </div>
                <div className="space-y-1.5">
                  <label
                    htmlFor="research-title"
                    className="block text-sm font-semibold"
                  >
                    Capture title{" "}
                    <span className="text-muted-foreground font-normal">
                      (optional)
                    </span>
                  </label>
                  <input
                    id="research-title"
                    maxLength={120}
                    value={title}
                    disabled={!!submission || !scope}
                    onChange={(event) => setTitle(event.target.value)}
                    className={CONTROL}
                    placeholder="For example, Ads health policy"
                  />
                </div>
                <div className="space-y-1.5">
                  <label
                    htmlFor="research-urls"
                    className="block text-sm font-semibold"
                  >
                    Public HTTPS URLs, one per line
                  </label>
                  <textarea
                    id="research-urls"
                    rows={3}
                    maxLength={8192}
                    value={urls}
                    disabled={!!submission || !scope}
                    onChange={(event) => setUrls(event.target.value)}
                    className={cn(CONTROL, "min-h-24 resize-y")}
                    placeholder="For example, https://support.google.com/adspolicy"
                    aria-describedby="research-url-note"
                  />
                  <p
                    id="research-url-note"
                    className="text-muted-foreground text-sm leading-relaxed"
                  >
                    The server checks each address is public before it opens it.
                    Keep private links and passwords out of this form.
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-3">
                  <Button
                    type="submit"
                    className="min-h-11 max-sm:w-full"
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
                {formNotice && (
                  <p role="alert" className="border-t pt-4 text-sm break-words">
                    {formNotice}
                  </p>
                )}
              </form>
            )}
          </div>
        </ScrollArea>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}

function CaptureReceipt({
  data,
  owner,
  scope,
  headingRef,
  notice,
  mayCancel,
  stopping,
  downloading,
  onStop,
  onDownload,
}: {
  data: BrowserResearch;
  owner: string | undefined;
  scope: string | undefined;
  headingRef: RefObject<HTMLHeadingElement | null>;
  notice: string | null;
  mayCancel: boolean;
  stopping: boolean;
  downloading: boolean;
  onStop: () => void;
  onDownload: () => void;
}) {
  const state = captureState(data.status);
  const pages = data.pages.length;
  return (
    <section
      aria-label="Capture evidence"
      className={cn(
        pageStyles.sheet,
        pageStyles.pin,
        data.status === "running" && "pinned",
        "mt-4 max-w-3xl min-w-0 space-y-5 p-4 sm:p-5",
      )}
    >
      <div className="space-y-1.5">
        <h3
          ref={headingRef}
          tabIndex={-1}
          className="text-lg leading-snug font-bold break-words focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
        >
          {data.title}
        </h3>
        <p
          role="status"
          className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm"
        >
          <StatusTag tone={state.tone}>{state.label}</StatusTag>
          <span className="text-muted-foreground">
            Started{" "}
            <time
              dateTime={toDateTimeAttr(data.created_at)}
              title={new Date(data.created_at).toLocaleString()}
            >
              {runTime(data.created_at)}
            </time>
            {data.status === "completed" && pages
              ? `, ${pages === 1 ? "1 page" : `${pages} pages`} saved`
              : ""}
          </span>
        </p>
        {data.last_error && (
          <p role="alert" className="text-destructive text-sm break-words">
            {browserWords(data.last_error)}
          </p>
        )}
      </div>
      {(isBrowserResearchBusy(data.status) || pages > 0) && (
        <div className="flex flex-wrap gap-2">
          {isBrowserResearchBusy(data.status) && (
            <Button
              variant="outline"
              className="min-h-11 max-sm:flex-1"
              disabled={!mayCancel || stopping}
              onClick={onStop}
            >
              <Square className="size-3" />
              {stopping ? "Stopping…" : "Stop capture"}
            </Button>
          )}
          {pages > 0 && (
            <Button
              variant="outline"
              className="min-h-11 max-sm:flex-1"
              disabled={downloading}
              onClick={onDownload}
            >
              <Download className="size-4" />
              Download evidence
            </Button>
          )}
        </div>
      )}
      {notice && (
        <p role="alert" className="text-sm break-words">
          {notice}
        </p>
      )}
      <div>
        <h4 className={cn(pageStyles.eyebrow, "mb-2")}>Pages</h4>
        {pages === 0 ? (
          <p className="text-muted-foreground text-sm">
            No page evidence has been retrieved.
          </p>
        ) : (
          <ol className="space-y-4">
            {data.pages.map((page) => {
              const source = publicResearchUrl(page.final_url || page.url);
              return (
                <li
                  key={page.index}
                  className="min-w-0 space-y-2 border-t pt-4 first:border-t-0 first:pt-0"
                >
                  <p className="text-sm font-semibold break-words">
                    {page.title || "Untitled captured page"}
                  </p>
                  {source ? (
                    <a
                      href={source}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-primary inline-flex min-h-11 max-w-full items-center gap-2 text-sm [overflow-wrap:anywhere] underline decoration-1 underline-offset-4"
                    >
                      <span className="min-w-0">{source}</span>
                      <ExternalLink
                        className="size-4 shrink-0"
                        aria-hidden="true"
                      />
                    </a>
                  ) : (
                    <p className="text-muted-foreground text-sm">
                      Source URL unavailable.
                    </p>
                  )}
                  <details>
                    <summary className="min-h-11 cursor-pointer py-3 text-sm font-semibold">
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
                </li>
              );
            })}
          </ol>
        )}
      </div>
      <div>
        <h4 className={cn(pageStyles.eyebrow, "mb-2")}>Record</h4>
        <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 text-sm">
          <dt className="text-muted-foreground">Browser minutes</dt>
          <dd>{data.usage.browser_minutes ?? "Not recorded"}</dd>
          <dt className="text-muted-foreground">Cost</dt>
          <dd>Not priced</dd>
          <dt className="text-muted-foreground">Cloud session</dt>
          <dd>
            {data.session_closed === true
              ? "Closed"
              : data.session_closed === false
                ? "Still open"
                : "Closure unconfirmed"}
          </dd>
        </dl>
      </div>
    </section>
  );
}
