"use client";

import * as Dialog from "@radix-ui/react-dialog";
import {
  ArrowDownToLine,
  ArrowLeftRight,
  ArrowRight,
  ArrowUpRight,
  Check,
  ChevronLeft,
  ChevronRight,
  Circle,
  CircleStop,
  Layers3,
  Network,
  Paintbrush,
  Plus,
  RefreshCw,
  Search,
  X,
} from "lucide-react";
import Link from "next/link";
import { useRef, useState } from "react";

import { PaperLayers } from "@/components/momentum/paper-layers";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { ThreadSubagentBatches } from "@/components/workspace/thread-subagent-batches";
import { useAgents } from "@/core/agents";
import { useAuth } from "@/core/auth/AuthProvider";
import { hasPermission, PERMISSIONS } from "@/core/auth/permissions";
import { useClients } from "@/core/clients";
import {
  useCancelConsoleRun,
  useConsoleRuns,
  useConsoleStats,
  useConsoleUsage,
  useConsoleUsageLedger,
  type ConsoleRunItem,
  type ConsoleStats,
} from "@/core/console";
import { useModels } from "@/core/models/hooks";
import { useSubagents } from "@/core/subagents";
import { pathOfThread } from "@/core/threads/utils";
import { formatCompactStamp } from "@/core/utils/datetime";

import { AgentTopology } from "./agent-topology";
import { useWorkspaceAppearance } from "./appearance-provider";
import {
  ArtifactLibraryView,
  ClientSpacesView,
  WorkflowsView,
} from "./business-views";
import { DispatchBoard } from "./dispatch-board";
import { modelDisplayName } from "./model-label";
import { MomentumGlyph } from "./momentum-glyph";
import {
  BRAIN_ASPECT,
  BRAIN_FLAT,
  BRAIN_LAYERS,
  MomoAvatar,
} from "./momo-avatar";
import { WorkspaceAppearance } from "./workspace-appearance";

import styles from "./command-center.module.css";

/**
 * The hero introduces the crew rather than repeating the lead card below it:
 * canon Momos by path (never copied; their lane owns the files), in paint
 * order, so the lead is drawn last and stands in front.
 */
const HERO_CREW = ["growth", "builder", "research", "dillon-brain"] as const;
const number = (value: number) => new Intl.NumberFormat("en-US").format(value);
const active = (status: string) => status === "pending" || status === "running";
/**
 * The backend stores 0 when a run never reported usage, so 0 tokens across
 * recorded runs is missing data, not a measurement (DESIGN.md, States).
 */
export function recordedTokens(stats: ConsoleStats | undefined) {
  if (!stats) return undefined;
  return stats.total_runs > 0 && stats.total_tokens === 0
    ? undefined
    : stats.total_tokens;
}
/** A run's token figure, or the reason there isn't one yet. */
export function runTokens(
  run: Pick<ConsoleRunItem, "status" | "total_tokens">,
) {
  if (run.total_tokens > 0) return `${number(run.total_tokens)} tokens`;
  return active(run.status) ? "Tokens still counting" : "Tokens not recorded";
}
const tabs = [
  "Mission Control",
  "Agent Studio",
  "Jobs",
  "Workflows",
  "Client Spaces",
  "Business Intelligence",
  "Artifact Library",
] as const;
type View = (typeof tabs)[number];

/*
 * Every tab's endpoint answers (checked on the rehearsal stack 2026-09-22),
 * but three of them promise more than the backend has: there is no client
 * tenancy, no revenue or billing feed, and no workspace-wide artifact index.
 * Those tabs say so instead of implying it.
 */
const PREVIEW_NOTES: Partial<Record<View, string>> = {
  "Client Spaces":
    "No clients have been added to this workspace yet. Once they are, they'll show up here with their assigned people and linked projects.",
  "Business Intelligence":
    "Token usage and provider attempts are recorded here. Revenue, margins and billing aren't connected yet.",
  "Artifact Library":
    "There's no workspace-wide artifact index yet. Choose a project to browse the files its conversations produced.",
};

/** Each view says what it holds; the brand line belongs to Mission Control. */
const VIEW_LEDES: Record<Exclude<View, "Mission Control">, string> = {
  "Agent Studio": "Your lead agent and the specialists it can hand work to.",
  Jobs: "Every recorded run, newest first, with its receipt.",
  Workflows: "Scheduled work and where each definition stands.",
  "Client Spaces": "Clients, the people assigned to them and their projects.",
  "Business Intelligence": "Recorded token usage and provider attempts.",
  "Artifact Library":
    "Files your conversations produced, one project at a time.",
};

function duration(seconds: number | null) {
  if (seconds === null) return "Not recorded";
  return seconds < 60
    ? `${Math.round(seconds)}s`
    : `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
}

function money(value: number | null | undefined, currency?: string | null) {
  if (value == null || !currency) return "Not priced";
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency,
      maximumFractionDigits: 4,
    }).format(value);
  } catch {
    return `${value.toFixed(4)} ${currency}`;
  }
}

function Status({ status }: { status: string }) {
  const label =
    {
      success: "Completed",
      error: "Failed",
      timeout: "Timed out",
      interrupted: "Interrupted",
    }[status] ?? status.charAt(0).toUpperCase() + status.slice(1);
  return (
    <span className={styles.status} data-status={status}>
      {status === "success" ? (
        <Check size={12} />
      ) : (
        <Circle size={9} fill="currentColor" />
      )}
      {label}
    </span>
  );
}

export function CommandCenter() {
  const { user } = useAuth();
  const { preferences } = useWorkspaceAppearance();
  const [appearanceOpen, setAppearanceOpen] = useState(false);
  const appearanceTrigger = useRef<HTMLButtonElement>(null);
  const canReadRuns = Boolean(user) && hasPermission(user, "runs:read");
  const clientsQuery = useClients();
  // Client Spaces stops being a preview once real clients exist (Momentum
  // Phase 2 item 2). Only a successful empty read may say "no clients": a
  // failed or pending read is unknown, not zero. Every other tab's
  // disclaimer is unaffected.
  const noClients = clientsQuery.isSuccess && clientsQuery.data.length === 0;
  const previewNotes: Partial<Record<View, string>> = noClients
    ? PREVIEW_NOTES
    : { ...PREVIEW_NOTES, "Client Spaces": undefined };
  const [view, setView] = useState<View>("Mission Control");
  const [filter, setFilter] = useState("");
  const [offset, setOffset] = useState(0);
  const [search, setSearch] = useState("");
  const [selectedAgentName, setSelectedAgentName] = useState<string | null>(
    null,
  );
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const receiptTrigger = useRef<HTMLElement | null>(null);
  const [cancelConfirm, setCancelConfirm] = useState(false);
  const stats = useConsoleStats();
  const runs = useConsoleRuns({ status: filter || undefined, offset });
  const activityRuns = useConsoleRuns({});
  const usage = useConsoleUsage();
  const usageLedger = useConsoleUsageLedger({ limit: 10 });
  const cancel = useCancelConsoleRun();
  const {
    subagents,
    isLoading: agentsLoading,
    error: agentsError,
  } = useSubagents();
  const { agents } = useAgents();
  const { models } = useModels();
  const modelName = (slug: string | null | undefined) =>
    modelDisplayName(slug, models);
  const lead =
    agents.find((agent) => agent.name === "dillon-brain") ?? agents[0];
  const startPath = lead
    ? pathOfThread("new", { agent_name: lead.name })
    : "/workspace/chats/new";
  const selectedAgent = subagents.find(
    (agent) => agent.name === selectedAgentName,
  );
  const selectedRun = runs.data?.runs.find(
    (run) => run.run_id === selectedRunId,
  );
  const visibleRuns =
    runs.data?.runs.filter((run) =>
      `${run.thread_title ?? ""} ${modelName(run.model_name)} ${run.run_id}`
        .toLowerCase()
        .includes(search.toLowerCase()),
    ) ?? [];
  // Two provider IDs can share one display name (the Contributor tier and
  // the plain model), so usage rows are merged by the name people see.
  const usageRows = Object.values(
    Object.entries(usage.data?.by_model ?? {}).reduce<
      Record<
        string,
        { model: string; tokens: number; runs: number; cost: number | null }
      >
    >((rows, [id, item]) => {
      const model = modelName(id) || "Model not recorded";
      const row = (rows[model] ??= { model, tokens: 0, runs: 0, cost: null });
      row.tokens += item.tokens;
      row.runs += item.runs;
      if (item.cost != null) row.cost = (row.cost ?? 0) + item.cost;
      return rows;
    }, {}),
  );
  const failedRuns = stats.data?.failed_runs;
  // Colour is state only: danger for a real failure, ok once runs exist and
  // none failed, plain ink otherwise.
  const errorState =
    failedRuns == null
      ? undefined
      : failedRuns > 0
        ? "danger"
        : stats.data?.total_runs
          ? "ok"
          : undefined;
  const displayedAgents = subagents.filter(
    (agent) => agent.source === "managed",
  );
  const roster = displayedAgents.length ? displayedAgents : subagents;
  // Running and queued are different states on the board, so the team
  // keeps them apart too: only a running run pins its agent. An agent with
  // a running run and a queued one is running.
  const agentsWith = (status: string) =>
    activityRuns.data?.runs
      .filter((run) => run.status === status)
      .map((run) => run.assistant_id)
      .filter((name): name is string => Boolean(name)) ?? null;
  const runningAgentNames = agentsWith("running");
  const queuedAgentNames =
    agentsWith("pending")?.filter(
      (name) => !(runningAgentNames ?? []).includes(name),
    ) ?? null;
  // Same guard as AgentTopology's lead state: an unknown live state must
  // never read as the lead working, and neither must a queued run.
  const heroBrainActive =
    canReadRuns &&
    activityRuns.isSuccess &&
    (runningAgentNames ?? []).includes("dillon-brain");

  function openRun(run: ConsoleRunItem) {
    receiptTrigger.current = document.activeElement as HTMLElement | null;
    setSelectedRunId(run.run_id);
    setCancelConfirm(false);
    cancel.reset();
  }

  /** A person-readable agent name for a run: never a raw id (DESIGN.md, Copy). */
  function agentLabel(assistantId: string | null) {
    if (!assistantId) return "Agent not recorded";
    if (assistantId === "lead" || assistantId === "lead_agent") {
      return lead?.display_name ?? "Default agent";
    }
    const known = subagents.find((agent) => agent.name === assistantId);
    if (known?.display_name) return known.display_name;
    return assistantId
      .split(/[-_]/)
      .filter(Boolean)
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
      .join(" ");
  }

  function runPath(run: ConsoleRunItem) {
    const agentName = agents.find(
      (agent) => agent.name === run.assistant_id,
    )?.name;
    return pathOfThread(
      run.thread_id,
      agentName ? { agent_name: agentName } : undefined,
    );
  }

  const refresh = () => {
    void stats.refetch();
    void runs.refetch();
    void usage.refetch();
  };

  const jobList = !canReadRuns ? (
    <p className={styles.notice} role="status">
      Run history is unavailable for this account.
    </p>
  ) : (
    <section className={styles.jobs} aria-labelledby="jobs-heading">
      <div className={styles.sectionHead}>
        <div>
          <h2 id="jobs-heading">
            {view === "Jobs" ? "Execution history" : "Latest assignments"}
          </h2>
          <p>Recorded runs across your conversations.</p>
        </div>
        <button
          className={styles.iconButton}
          onClick={refresh}
          aria-label="Refresh work"
          disabled={runs.isFetching}
        >
          <RefreshCw
            size={17}
            className={runs.isFetching ? styles.spin : undefined}
          />
        </button>
      </div>
      <div className={styles.filters}>
        <label className={styles.search}>
          <Search size={16} />
          <input
            aria-label="Search loaded jobs"
            placeholder="Search this page"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </label>
        <select
          aria-label="Filter jobs by status"
          value={filter}
          onChange={(event) => {
            setFilter(event.target.value);
            setOffset(0);
            setSelectedRunId(null);
          }}
        >
          <option value="">All states</option>
          <option value="running">Running</option>
          <option value="pending">Pending</option>
          <option value="success">Completed</option>
          <option value="error">Error</option>
          <option value="interrupted">Interrupted</option>
          <option value="timeout">Timeout</option>
        </select>
      </div>
      {runs.isError ? (
        <div className={styles.empty} role="alert">
          <h3>Work history is unavailable</h3>
          <p>{runs.error.message}</p>
          <button onClick={() => void runs.refetch()}>Try again</button>
        </div>
      ) : runs.isLoading ? (
        <div className={styles.empty} role="status">
          Loading your work history…
        </div>
      ) : visibleRuns.length === 0 ? (
        <div className={styles.empty}>
          <Layers3 size={28} />
          <h3>
            {search || filter
              ? "No matching assignments"
              : "Your first mission starts here"}
          </h3>
          <p>
            {search || filter
              ? "Change the filter or search to see more work."
              : "Start a conversation with your lead agent. Its execution receipt will appear here."}
          </p>
          {!search && !filter && (
            <Link className={styles.textLink} href={startPath}>
              Start a mission <ArrowRight size={15} />
            </Link>
          )}
        </div>
      ) : (
        <div className={styles.jobRows}>
          {visibleRuns.map((run) => {
            const title = run.thread_title ?? "Untitled assignment";
            const stamp = formatCompactStamp(run.created_at, "en-US");
            return (
              <button
                className={styles.jobRow}
                key={run.run_id}
                aria-pressed={selectedRunId === run.run_id}
                onClick={() => openRun(run)}
                title={title}
              >
                <span className={styles.jobIcon} data-status={run.status}>
                  <MomentumGlyph seed={`thread:${run.thread_id}`} size={34} />
                </span>
                <span className={styles.jobName}>
                  <strong>{title}</strong>
                  <small>
                    {stamp && run.created_at && (
                      <>
                        <time
                          className={styles.metaStamp}
                          dateTime={run.created_at}
                        >
                          {stamp}
                        </time>{" "}
                        <span aria-hidden="true">·</span>{" "}
                      </>
                    )}
                    <span className={styles.metaModel}>
                      {modelName(run.model_name) || "Model not recorded"}
                    </span>{" "}
                    <span aria-hidden="true">·</span>{" "}
                    <span className={styles.metaTokens}>{runTokens(run)}</span>
                  </small>
                </span>
                <Status status={run.status} />
                <ChevronRight size={16} />
              </button>
            );
          })}
        </div>
      )}
      <div className={styles.pagination}>
        <span>Page {Math.floor(offset / 20) + 1} · up to 20 runs</span>
        <div>
          <button
            aria-label="Previous jobs page"
            disabled={offset === 0 || runs.isFetching}
            onClick={() => {
              setOffset(Math.max(0, offset - 20));
              setSelectedRunId(null);
            }}
          >
            <ChevronLeft size={16} />
          </button>
          <button
            aria-label="Next jobs page"
            disabled={!runs.data?.has_more || runs.isFetching}
            onClick={() => {
              setOffset(offset + 20);
              setSelectedRunId(null);
            }}
          >
            <ChevronRight size={16} />
          </button>
        </div>
      </div>
    </section>
  );

  const team = (
    <section className={styles.team} aria-labelledby="team-heading">
      <div className={styles.sectionHead}>
        <div>
          <h2 id="team-heading">Your agent team</h2>
          <p>Specialists, connected by a common mission.</p>
        </div>
        <Network size={21} />
      </div>
      <AgentTopology
        leadLabel={lead?.display_name ?? lead?.name ?? "Lead agent"}
        leadHref={startPath}
        roster={roster}
        selectedName={selectedAgentName}
        loading={agentsLoading}
        error={Boolean(agentsError)}
        runtimeKnown={canReadRuns && activityRuns.isSuccess}
        runningAgentNames={runningAgentNames}
        queuedAgentNames={queuedAgentNames}
        onSelect={setSelectedAgentName}
      />
      {selectedAgent ? (
        <div className={styles.agentDetail}>
          <div className={styles.sectionHead}>
            <div className={styles.selectedIdentity}>
              <span aria-hidden="true">
                <MomoAvatar agent={selectedAgent} size={40} />
              </span>
              <div>
                <h3>{selectedAgent.display_name ?? selectedAgent.name}</h3>
                <span>Role &amp; working brief</span>
              </div>
            </div>
            <button
              className={styles.iconButton}
              aria-label="Close specialist details"
              onClick={() => setSelectedAgentName(null)}
            >
              <X size={16} />
            </button>
          </div>
          <p>{selectedAgent.description}</p>
          {user?.system_role === "admin" && selectedAgent.editable && (
            <Link
              className={styles.textLink}
              href="/workspace/command-center?settings=subagents"
            >
              Edit specialist brief <ArrowUpRight size={14} />
            </Link>
          )}
          <dl>
            <div>
              <dt>Model</dt>
              <dd>
                {selectedAgent.model === "inherit"
                  ? "Inherits lead model"
                  : modelName(selectedAgent.model) || "Not recorded"}
              </dd>
            </div>
            <div>
              <dt>Execution limits</dt>
              <dd>
                {selectedAgent.max_turns} turns ·{" "}
                {selectedAgent.timeout_seconds}s timeout
              </dd>
            </div>
            <div>
              <dt>Tools</dt>
              <dd>{selectedAgent.tools?.join(", ") ?? "Runtime defaults"}</dd>
            </div>
          </dl>
        </div>
      ) : (
        <p className={styles.agentHint}>
          Select a specialist to inspect its role, tools and limits.
        </p>
      )}
    </section>
  );

  return (
    // A div, not <main>: the workspace shell's SidebarInset is already the
    // page's main landmark, and a second one nested inside it confuses
    // landmark navigation.
    <div
      className={styles.root}
      data-live={stats.data?.active_runs ? "true" : "false"}
      data-treatment={preferences.treatment}
      data-appearance-open={appearanceOpen}
    >
      <header className={styles.topbar}>
        <div className={styles.brand}>
          <SidebarTrigger />
          <span className={styles.appName}>Command Center</span>
        </div>
        <span className={styles.account}>Your workspace</span>
      </header>
      <div className={styles.content}>
        <div className={styles.heading}>
          <div className={styles.headingText}>
            <h1>{view}</h1>
            <p className={styles.headingCopy}>
              {view === "Mission Control" ? (
                <>
                  <span>Give your ambition a team.</span> Keep the work in view.
                </>
              ) : (
                VIEW_LEDES[view]
              )}
            </p>
          </div>
          {/* The page's one loud moment: the crew on a kraft scrap, as on the
              landing, lead in front. No brass pins here: on this page a pin
              means a specialist is working. The sidebar carries the wordmark. */}
          <div className={styles.heroArt} aria-hidden="true">
            <span className={`${styles.heroScrap} paper-torn`} />
            {HERO_CREW.map((slug) =>
              slug === "dillon-brain" ? (
                // Its box is sized by .heroMomo's own CSS (percentage width,
                // aspect-ratio); PaperLayers fills it, [data-paper-layers]
                // overriding its usual fixed pixel box for this one site.
                <span key={slug} className={styles.heroMomo} data-crew={slug}>
                  <PaperLayers
                    layers={BRAIN_LAYERS}
                    flatSrc={BRAIN_FLAT}
                    size={160}
                    aspectRatio={BRAIN_ASPECT}
                    state={heroBrainActive ? "working" : "idle"}
                  />
                </span>
              ) : (
                <img
                  key={slug}
                  className={styles.heroMomo}
                  data-crew={slug}
                  src={`/momentum/momos/${slug}.svg`}
                  alt=""
                  width={160}
                  height={160}
                />
              ),
            )}
          </div>
          <div className={styles.headingActions}>
            <Link className={styles.primary} href={startPath}>
              <Plus size={17} />
              Start a mission
            </Link>
            <button
              ref={appearanceTrigger}
              className={styles.appearanceButton}
              type="button"
              aria-expanded={appearanceOpen}
              aria-controls="workspace-appearance"
              onClick={() => setAppearanceOpen(!appearanceOpen)}
            >
              <Paintbrush size={16} /> Appearance
            </button>
          </div>
        </div>
        {appearanceOpen && (
          <WorkspaceAppearance
            onClose={() => {
              setAppearanceOpen(false);
              appearanceTrigger.current?.focus();
            }}
          />
        )}
        <nav className={styles.tabs} aria-label="Command Center views">
          {tabs.map((tab) => (
            <button
              key={tab}
              aria-current={view === tab ? "page" : undefined}
              onClick={() => {
                setView(tab);
                setSelectedRunId(null);
              }}
            >
              {tab}
              {previewNotes[tab] && (
                <>
                  {" "}
                  <span className={styles.previewTag}>Preview</span>
                </>
              )}
            </button>
          ))}
        </nav>
        {!canReadRuns ? (
          <p className={styles.notice} role="status">
            Run history and usage are unavailable for this account.
          </p>
        ) : stats.isError ? (
          <div className={styles.notice} role="alert">
            Workspace totals couldn&apos;t be loaded.{" "}
            <button onClick={() => void stats.refetch()}>Retry</button>
          </div>
        ) : (
          // A labelled, focusable region: below 640px this row scrolls
          // sideways, and a scroller has to be reachable from the keyboard.
          <div
            className={styles.metrics}
            role="region"
            aria-label="Your recorded runs, all time"
            tabIndex={0}
          >
            {[
              {
                label: "Active runs",
                value: stats.data?.active_runs,
                scope: "Right now",
              },
              {
                label: "Recorded runs",
                value: stats.data?.total_runs,
                scope: "All time, your runs",
              },
              {
                label: "Errors & timeouts",
                value: failedRuns,
                state: errorState,
                scope: "All time, your runs",
              },
              {
                label: "Recorded tokens",
                value: recordedTokens(stats.data),
                missing:
                  stats.data?.total_tokens === 0 ? "Not recorded" : undefined,
                scope: "All time, input and output",
              },
            ].map((metric) => (
              <div key={metric.label} data-state={metric.state}>
                <span>{metric.label}</span>
                <strong>
                  {stats.isLoading ? (
                    <span>Loading</span>
                  ) : metric.value == null ? (
                    <span>{metric.missing ?? "Unavailable"}</span>
                  ) : (
                    number(metric.value)
                  )}
                </strong>
                <small>{metric.scope}</small>
              </div>
            ))}
          </div>
        )}
        {previewNotes[view] && (
          <p className={styles.previewNote}>
            <span className={styles.previewTag}>Preview</span>{" "}
            {previewNotes[view]}
          </p>
        )}
        {view === "Mission Control" ? (
          <>
            {/* The work leads at every width (DESIGN.md, Layout): the
                dispatch board comes first in the DOM, then the team, so the
                keyboard walks the page in the order it reads. */}
            {canReadRuns ? (
              <DispatchBoard
                runs={activityRuns.data?.runs}
                loading={activityRuns.isLoading}
                error={activityRuns.isError ? activityRuns.error.message : null}
                onRetry={() => void activityRuns.refetch()}
                onOpen={openRun}
                selectedRunId={selectedRunId}
                agentLabel={agentLabel}
                startPath={startPath}
                onShowAll={() => setView("Jobs")}
                hasMore={Boolean(activityRuns.data?.has_more)}
                panelClassName={styles.jobs}
                headClassName={styles.sectionHead}
              />
            ) : (
              jobList
            )}
            <div className={styles.missionTeam}>{team}</div>
            <nav className={styles.destinations} aria-label="Workspace tools">
              <span>Also in your workspace</span>
              <Link href="/workspace/agents">
                Agents <ArrowUpRight size={15} aria-hidden="true" />
              </Link>
              <Link href="/workspace/scheduled-tasks">
                Scheduled tasks <ArrowUpRight size={15} aria-hidden="true" />
              </Link>
              <Link href="/workspace/capabilities">
                Capability Center <ArrowUpRight size={15} aria-hidden="true" />
              </Link>
            </nav>
          </>
        ) : null}
        {view === "Agent Studio" ? (
          <div className={styles.studio}>{team}</div>
        ) : null}
        {view === "Jobs" ? jobList : null}
        {view === "Workflows" ? <WorkflowsView /> : null}
        {view === "Client Spaces" ? <ClientSpacesView /> : null}
        {view === "Artifact Library" ? <ArtifactLibraryView /> : null}
        {view === "Business Intelligence" ? (
          <section className={styles.usage}>
            <div className={styles.sectionHead}>
              <div>
                <h2>Operational intelligence</h2>
                <p>Last 14 days · current account only</p>
              </div>
              <strong>
                {money(usage.data?.total_cost, usage.data?.currency)}
              </strong>
            </div>
            {!canReadRuns ? (
              <p role="status">Usage is unavailable for this account.</p>
            ) : usage.isError ? (
              <div className={styles.empty} role="alert">
                <p>Usage couldn&apos;t be loaded.</p>
                <button onClick={() => void usage.refetch()}>Try again</button>
              </div>
            ) : usage.isLoading ? (
              <p role="status">Loading usage…</p>
            ) : (
              <>
                <p className={styles.scrollHint}>
                  <ArrowLeftRight size={14} aria-hidden="true" />
                  Scroll charts and tables sideways to see all values.
                </p>
                <div
                  className={styles.usageChart}
                  role="img"
                  aria-label="Daily token usage for the last 14 days"
                  tabIndex={0}
                >
                  {usage.data?.days.map((day) => (
                    <div
                      key={day.date}
                      title={`${day.date}: ${number(day.total_tokens)} tokens, ${day.runs} runs`}
                    >
                      <span>{number(day.total_tokens)}</span>
                      <i
                        style={{
                          height: `${Math.max(2, (day.total_tokens / Math.max(1, ...usage.data.days.map((item) => item.total_tokens))) * 125)}px`,
                        }}
                      />
                      <small>{day.date.slice(5)}</small>
                    </div>
                  ))}
                </div>
                <div
                  className={styles.tableWrap}
                  role="region"
                  aria-label="Model usage table"
                  tabIndex={0}
                >
                  <table>
                    <caption>Model usage in this period</caption>
                    <thead>
                      <tr>
                        <th>Model</th>
                        <th>Tokens</th>
                        <th>Runs</th>
                        <th>Estimated cost</th>
                      </tr>
                    </thead>
                    <tbody>
                      {usageRows.map((row) => (
                        <tr key={row.model}>
                          <th scope="row">{row.model}</th>
                          <td>{number(row.tokens)}</td>
                          <td>{number(row.runs)}</td>
                          <td>{money(row.cost, usage.data?.currency)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {usageRows.length === 0 && (
                  <p>No model usage was recorded in this period.</p>
                )}
                <p className={styles.diagramNote}>
                  Cost estimates cover priced models only. Unpriced usage
                  isn&apos;t free; these figures aren&apos;t your provider
                  balance or invoice.
                </p>
                <div className={`${styles.sectionHead} ${styles.ledgerHead}`}>
                  <div>
                    <h2>Provider attempt ledger</h2>
                    <p>
                      Read-only attempt and retry evidence; this view
                      doesn&apos;t approve, block, or authorize provider spend.
                    </p>
                  </div>
                  <button
                    className={styles.iconButton}
                    onClick={() => void usageLedger.refetch()}
                    aria-label="Refresh provider attempt ledger"
                    disabled={usageLedger.isFetching}
                  >
                    <RefreshCw
                      size={17}
                      className={
                        usageLedger.isFetching ? styles.spin : undefined
                      }
                    />
                  </button>
                </div>
                {usageLedger.isError ? (
                  <div className={styles.empty} role="alert">
                    <p>Provider attempt evidence couldn&apos;t be loaded.</p>
                    <button onClick={() => void usageLedger.refetch()}>
                      Try again
                    </button>
                  </div>
                ) : usageLedger.isLoading ? (
                  <p role="status">Loading provider attempts…</p>
                ) : usageLedger.data?.attempts.length ? (
                  <div
                    className={styles.tableWrap}
                    role="region"
                    aria-label="Provider attempt ledger table"
                    tabIndex={0}
                  >
                    <table className={styles.ledgerTable}>
                      <caption>
                        Latest provider attempts with tokens, status, latency
                        and cost evidence
                      </caption>
                      <thead>
                        <tr>
                          <th>Attempt</th>
                          <th>Status</th>
                          <th>Provider / model</th>
                          <th>Tokens</th>
                          <th>Latency</th>
                          <th>Provider cost</th>
                          <th>Configured estimate</th>
                        </tr>
                      </thead>
                      <tbody>
                        {usageLedger.data.attempts.map((attempt) => (
                          <tr key={attempt.event_id}>
                            <th scope="row">
                              {attempt.provider_attempt_id ??
                                `Call ${attempt.llm_call_index ?? "?"}`}
                              <span className={styles.meta}>
                                {attempt.created_at
                                  ? new Date(
                                      attempt.created_at,
                                    ).toLocaleString()
                                  : "Time not recorded"}
                              </span>
                            </th>
                            <td>
                              <span
                                className={styles.status}
                                data-status={
                                  attempt.attempt_status === "success"
                                    ? "success"
                                    : "error"
                                }
                              >
                                {attempt.attempt_status}
                              </span>
                              {attempt.error_type && (
                                <span className={styles.meta}>
                                  {attempt.error_type}
                                </span>
                              )}
                            </td>
                            <td>
                              {attempt.provider ?? "Provider not recorded"}
                              <span className={styles.meta}>
                                {modelName(
                                  attempt.resolved_model ??
                                    attempt.requested_model,
                                ) || "Model not recorded"}
                              </span>
                            </td>
                            <td>
                              {number(attempt.total_tokens)}
                              <span className={styles.meta}>
                                {number(attempt.input_tokens)} in ·{" "}
                                {number(attempt.output_tokens)} out
                                {attempt.cache_read_tokens
                                  ? ` · ${number(attempt.cache_read_tokens)} cached`
                                  : ""}
                              </span>
                            </td>
                            <td>
                              {attempt.latency_ms == null
                                ? "Not recorded"
                                : `${number(attempt.latency_ms)}ms`}
                            </td>
                            <td>
                              {money(
                                attempt.provider_reported_cost,
                                attempt.provider_reported_currency,
                              )}
                            </td>
                            <td>
                              {money(
                                attempt.estimated_cost,
                                attempt.estimated_currency,
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {usageLedger.data.has_more && (
                      <p className={styles.diagramNote}>
                        Showing the latest 10 attempts. The API has more
                        evidence available for audit views.
                      </p>
                    )}
                  </div>
                ) : (
                  <p>
                    No provider attempts were recorded in the latest ledger.
                  </p>
                )}
              </>
            )}
          </section>
        ) : null}
        <footer className={styles.footer}>
          <span>Momentum · Built for the work ahead.</span>
          <span>No model calls from this dashboard</span>
        </footer>
      </div>
      {selectedRun && (
        <Dialog.Root
          open
          onOpenChange={(open) => !open && setSelectedRunId(null)}
        >
          <Dialog.Overlay className={styles.runBackdrop} />
          <Dialog.Content
            asChild
            aria-describedby={undefined}
            onCloseAutoFocus={(event) => {
              event.preventDefault();
              receiptTrigger.current?.focus();
            }}
          >
            <aside
              className={styles.runDetail}
              aria-labelledby="run-detail-heading"
            >
              <div className={styles.sectionHead}>
                <Dialog.Title asChild>
                  <h2 id="run-detail-heading">Execution receipt</h2>
                </Dialog.Title>
                <button
                  className={styles.iconButton}
                  aria-label="Close execution receipt"
                  onClick={() => setSelectedRunId(null)}
                >
                  <X size={20} />
                </button>
              </div>
              <Status status={selectedRun.status} />
              <h3>{selectedRun.thread_title ?? "Untitled assignment"}</h3>
              <dl>
                <div>
                  <dt>Model</dt>
                  <dd>{modelName(selectedRun.model_name) || "Not recorded"}</dd>
                </div>
                <div>
                  <dt>Duration</dt>
                  <dd>{duration(selectedRun.duration_seconds)}</dd>
                </div>
                <div>
                  <dt>Tokens</dt>
                  <dd>
                    {selectedRun.total_tokens > 0
                      ? number(selectedRun.total_tokens)
                      : active(selectedRun.status)
                        ? "Still counting"
                        : "Not recorded"}
                  </dd>
                </div>
                <div>
                  <dt>Estimated cost</dt>
                  <dd>{money(selectedRun.cost, stats.data?.currency)}</dd>
                </div>
                <div>
                  <dt>Run ID</dt>
                  <dd>{selectedRun.run_id}</dd>
                </div>
                <div>
                  <dt>Started</dt>
                  <dd>
                    {selectedRun.created_at
                      ? new Date(selectedRun.created_at).toLocaleString()
                      : "Not recorded"}
                  </dd>
                </div>
              </dl>
              {selectedRun.error && (
                <p className={styles.notice} role="alert">
                  {selectedRun.error}
                </p>
              )}
              <Link className={styles.primary} href={runPath(selectedRun)}>
                Open conversation &amp; artifacts <ArrowRight size={16} />
              </Link>
              <div className={styles.batchControls}>
                <ThreadSubagentBatches threadId={selectedRun.thread_id} />
              </div>
              {active(selectedRun.status) &&
                hasPermission(user, PERMISSIONS.RUNS_CANCEL) && (
                  <div className={styles.cancel}>
                    {cancelConfirm ? (
                      <>
                        <p>
                          Stop this run? Completed tool actions will remain.
                        </p>
                        <button
                          disabled={cancel.isPending}
                          onClick={() =>
                            cancel.mutate(
                              {
                                threadId: selectedRun.thread_id,
                                runId: selectedRun.run_id,
                              },
                              { onSuccess: () => setCancelConfirm(false) },
                            )
                          }
                        >
                          <CircleStop size={16} />
                          {cancel.isPending
                            ? "Requesting stop…"
                            : "Confirm stop"}
                        </button>
                        <button
                          disabled={cancel.isPending}
                          onClick={() => setCancelConfirm(false)}
                        >
                          Keep running
                        </button>
                      </>
                    ) : (
                      <button onClick={() => setCancelConfirm(true)}>
                        <CircleStop size={16} />
                        Stop run
                      </button>
                    )}
                  </div>
                )}
              {cancel.isError && <p role="alert">{cancel.error.message}</p>}
              <p className={styles.diagramNote}>
                <ArrowDownToLine size={14} /> Artifact downloads and complete
                task timelines are available in the conversation. Batch
                pause/resume appears when supported by the runtime.
              </p>
            </aside>
          </Dialog.Content>
        </Dialog.Root>
      )}
    </div>
  );
}
