"use client";

import * as Dialog from "@radix-ui/react-dialog";
import {
  ArrowDownToLine,
  ArrowLeftRight,
  ArrowRight,
  ArrowUpRight,
  Bot,
  Check,
  ChevronLeft,
  ChevronRight,
  Circle,
  CircleStop,
  Clock3,
  Layers3,
  Network,
  Paintbrush,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  X,
} from "lucide-react";
import Link from "next/link";
import { useRef, useState } from "react";

import { SidebarTrigger } from "@/components/ui/sidebar";
import { ThreadSubagentBatches } from "@/components/workspace/thread-subagent-batches";
import { useAgents } from "@/core/agents";
import { useAuth } from "@/core/auth/AuthProvider";
import { hasPermission, PERMISSIONS } from "@/core/auth/permissions";
import {
  useCancelConsoleRun,
  useConsoleRuns,
  useConsoleStats,
  useConsoleUsage,
  useConsoleUsageLedger,
  type ConsoleRunItem,
} from "@/core/console";
import { useSubagents } from "@/core/subagents";
import { pathOfThread } from "@/core/threads/utils";

import { AgentTopology } from "./agent-topology";
import { useWorkspaceAppearance } from "./appearance-provider";
import { BrandSignature } from "./brand-signature";
import {
  ArtifactLibraryView,
  ClientSpacesView,
  WorkflowsView,
} from "./business-views";
import { MomentumGlyph } from "./momentum-glyph";
import { BrandMotionToggle, WorkspaceAppearance } from "./workspace-appearance";

import styles from "./command-center.module.css";

const number = (value: number) => new Intl.NumberFormat("en-US").format(value);
const active = (status: string) => status === "pending" || status === "running";
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
      `${run.thread_title ?? ""} ${run.model_name ?? ""} ${run.run_id}`
        .toLowerCase()
        .includes(search.toLowerCase()),
    ) ?? [];
  const displayedAgents = subagents.filter(
    (agent) => agent.source === "managed",
  );
  const roster = displayedAgents.length ? displayedAgents : subagents;
  const activeAgentNames =
    activityRuns.data?.runs
      .filter((run) => active(run.status))
      .map((run) => run.assistant_id)
      .filter((name): name is string => Boolean(name)) ?? null;

  function openRun(run: ConsoleRunItem) {
    receiptTrigger.current = document.activeElement as HTMLElement | null;
    setSelectedRunId(run.run_id);
    setCancelConfirm(false);
    cancel.reset();
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
          {visibleRuns.map((run) => (
            <button
              className={styles.jobRow}
              key={run.run_id}
              aria-pressed={selectedRunId === run.run_id}
              onClick={() => openRun(run)}
            >
              <span className={styles.jobIcon} data-status={run.status}>
                <MomentumGlyph seed={`thread:${run.thread_id}`} size={34} />
              </span>
              <span className={styles.jobName}>
                <strong>{run.thread_title ?? "Untitled assignment"}</strong>
                <small>
                  <span className={styles.metaModel}>
                    {run.model_name ?? "Model not recorded"}
                  </span>{" "}
                  <span aria-hidden="true">·</span>{" "}
                  <span className={styles.metaTokens}>
                    {number(run.total_tokens)} tokens
                  </span>
                </small>
              </span>
              <Status status={run.status} />
              <ChevronRight size={16} />
            </button>
          ))}
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
        activeAgentNames={activeAgentNames}
        onSelect={setSelectedAgentName}
      />
      {selectedAgent ? (
        <div className={styles.agentDetail}>
          <div className={styles.sectionHead}>
            <div className={styles.selectedIdentity}>
              <MomentumGlyph seed={`agent:${selectedAgent.name}`} size={58} />
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
                  : selectedAgent.model}
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
    <main
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
          <div>
            <h1>{view}</h1>
            <p className={styles.headingCopy}>
              <span>Give your ambition a team.</span>{" "}
              <span>Keep the work in view.</span>
            </p>
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
          <div className={styles.brandStage}>
            <BrandSignature size="hero" />
            <BrandMotionToggle />
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
            </button>
          ))}
        </nav>
        {!canReadRuns ? (
          <p className={styles.notice} role="status">
            Run history and usage are unavailable for this account.
          </p>
        ) : stats.isError ? (
          <div className={styles.notice} role="alert">
            Workspace totals could not be loaded.{" "}
            <button onClick={() => void stats.refetch()}>Retry</button>
          </div>
        ) : (
          <div
            className={styles.metrics}
            aria-label="Recorded workspace totals"
          >
            {[
              { label: "Active runs", value: stats.data?.active_runs },
              { label: "Recorded runs", value: stats.data?.total_runs },
              { label: "Errors & timeouts", value: stats.data?.failed_runs },
              { label: "Recorded tokens", value: stats.data?.total_tokens },
            ].map((metric) => (
              <div key={metric.label}>
                <span>{metric.label}</span>
                <strong>
                  {stats.isLoading || metric.value === undefined
                    ? "—"
                    : number(metric.value)}
                </strong>
              </div>
            ))}
          </div>
        )}
        {view === "Mission Control" ? (
          <>
            <div className={styles.overview}>
              {team}
              {jobList}
            </div>
            <section
              className={styles.destinations}
              aria-label="Workspace tools"
            >
              <Link href="/workspace/agents">
                <Bot size={20} />
                <div>
                  <strong>Agent workspace</strong>
                  <span>Configure your lead agents</span>
                </div>
                <ArrowUpRight size={17} />
              </Link>
              <Link href="/workspace/scheduled-tasks">
                <Clock3 size={20} />
                <div>
                  <strong>Scheduled work</strong>
                  <span>Inspect schedules and run history</span>
                </div>
                <ArrowUpRight size={17} />
              </Link>
              <Link href="/workspace/capabilities">
                <ShieldCheck size={20} />
                <div>
                  <strong>Connected capabilities</strong>
                  <span>Manage skills and integrations</span>
                </div>
                <ArrowUpRight size={17} />
              </Link>
            </section>
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
                <p>Usage could not be loaded.</p>
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
                      {Object.entries(usage.data?.by_model ?? {}).map(
                        ([model, item]) => (
                          <tr key={model}>
                            <th scope="row">{model}</th>
                            <td>{number(item.tokens)}</td>
                            <td>{number(item.runs)}</td>
                            <td>{money(item.cost, usage.data?.currency)}</td>
                          </tr>
                        ),
                      )}
                    </tbody>
                  </table>
                </div>
                {Object.keys(usage.data?.by_model ?? {}).length === 0 && (
                  <p>No model usage was recorded in this period.</p>
                )}
                <p className={styles.diagramNote}>
                  Cost estimates cover priced models only. Unpriced usage is not
                  free; these figures are not your provider balance or invoice.
                  Client revenue, margins and billing are not connected.
                </p>
                <div className={styles.sectionHead}>
                  <div>
                    <h2>Provider attempt ledger</h2>
                    <p>
                      Read-only attempt and retry evidence; this view does not
                      approve, block, or authorize provider spend.
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
                    <p>Provider attempt evidence could not be loaded.</p>
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
                                {attempt.resolved_model ??
                                  attempt.requested_model ??
                                  "Model not recorded"}
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
          <span>Powered by DeerFlow · No model calls from this dashboard</span>
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
                  <dd>{selectedRun.model_name ?? "Not recorded"}</dd>
                </div>
                <div>
                  <dt>Duration</dt>
                  <dd>{duration(selectedRun.duration_seconds)}</dd>
                </div>
                <div>
                  <dt>Tokens</dt>
                  <dd>{number(selectedRun.total_tokens)}</dd>
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
    </main>
  );
}
