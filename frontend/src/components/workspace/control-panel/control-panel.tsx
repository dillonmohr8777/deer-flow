"use client";

import { useQuery } from "@tanstack/react-query";
import {
  ArrowRightIcon,
  BarChart3Icon,
  CalendarClockIcon,
  CheckCircle2Icon,
  CircleIcon,
  ClipboardCheckIcon,
  FileTextIcon,
  GraduationCapIcon,
  InboxIcon,
  MessageSquarePlusIcon,
  PlusIcon,
  ShieldCheckIcon,
  SparklesIcon,
  Trash2Icon,
  UsersIcon,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { pageStyles, StatusTag } from "@/components/workspace/page-body";
import {
  BUSINESS_OWNER_LESSONS,
  readStartHereProgress,
} from "@/components/workspace/start-here/start-here-data";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useAgents } from "@/core/agents/hooks";
import { fetch as apiFetch } from "@/core/api/fetcher";
import { useAuth, useIsClient } from "@/core/auth/AuthProvider";
import { getBackendBaseURL } from "@/core/config";
import { isStaticWebsiteOnly } from "@/core/static-mode";
import { useWorkspaceSelection } from "@/core/workspaces/hooks";
import { cn } from "@/lib/utils";

import {
  buildChatPromptHref,
  CONNECT_REPORTING_PROMPT,
  CREATE_SOMETHING_CARDS,
  DAY_ONE_CHECKLIST,
  KICKOFF_ROADMAP_PHASES,
  MEETING_NOTES_PROMPT,
  readActionItems,
  readChecklistState,
  REPORTING_CONNECTIONS,
  WORKSPACE_TEAM_ROLES,
  writeActionItems,
  writeChecklistState,
  type LocalActionItem,
} from "./control-panel-data";

import styles from "./control-panel.module.css";

type PortalDeliverable = {
  id: string;
  subject: string;
  state: string;
};

type PortalRoster = {
  workspace_id: string;
  clients: { id: string; name: string }[];
};

const RING_RADIUS = 26;
const RING_CIRCUMFERENCE = 2 * Math.PI * RING_RADIUS;

const DELIVERABLE_STATE_LABELS: Record<
  string,
  { label: string; tone: "ok" | "active" | "attention" | "idle" }
> = {
  pending: { label: "Pending", tone: "idle" },
  running: { label: "Momo is working", tone: "active" },
  needs_approval: { label: "Needs approval", tone: "attention" },
  published: { label: "Published", tone: "ok" },
};

type PortalDeliverablesResult = {
  items: PortalDeliverable[];
  activeCount: number;
  hasMore: boolean;
};

// Backend /api/client-portal/threads accepts "all" | "pending" | "needs_approval" | "published".
// Threads actively being worked by Momo (state="running") have no approval_id or published_id yet,
// so they are returned under state=pending and labeled state="running" by the server summary.
const PORTAL_ACTIVE_QUERY_STATES = ["pending", "needs_approval"] as const;
const ACTIVE_DELIVERABLE_STATES = new Set([
  "pending",
  "running",
  "needs_approval",
]);
const DELIVERABLES_PAGE_SIZE = 100;
const MAX_DELIVERABLES_PAGES = 5;

async function fetchActiveStateThreads(
  workspaceId: string,
  state: (typeof PORTAL_ACTIVE_QUERY_STATES)[number],
  signal?: AbortSignal,
): Promise<{ threads: PortalDeliverable[]; hasMore: boolean }> {
  const collected: PortalDeliverable[] = [];
  let offset = 0;
  let hasMore = false;
  for (let page = 0; page < MAX_DELIVERABLES_PAGES; page += 1) {
    const listRes = await apiFetch(
      `${getBackendBaseURL()}/api/client-portal/threads?state=${state}&limit=${DELIVERABLES_PAGE_SIZE}&offset=${offset}`,
      {
        signal,
        cache: "no-store",
        headers: { "X-Portal-Workspace": workspaceId },
      },
    );
    if (!listRes.ok) {
      throw new Error(
        `Failed to load active deliverables (HTTP ${listRes.status})`,
      );
    }
    const data = (await listRes.json()) as {
      threads?: PortalDeliverable[];
      has_more?: boolean;
    };
    const batch = Array.isArray(data.threads) ? data.threads : [];
    collected.push(...batch);
    hasMore = Boolean(data.has_more);
    if (!hasMore || batch.length === 0) {
      break;
    }
    offset += batch.length;
  }
  return { threads: collected, hasMore };
}

async function fetchPortalDeliverables(
  selectedWorkspaceId: string | null,
  signal?: AbortSignal,
): Promise<PortalDeliverablesResult> {
  const rosterRes = await apiFetch(
    `${getBackendBaseURL()}/api/client-portal/clients`,
    {
      signal,
      cache: "no-store",
      headers: selectedWorkspaceId
        ? { "X-Portal-Workspace": selectedWorkspaceId }
        : undefined,
    },
  );
  if (!rosterRes.ok) {
    throw new Error(
      `Failed to load workspace deliverables (HTTP ${rosterRes.status})`,
    );
  }
  const roster = (await rosterRes.json()) as PortalRoster;
  const portalWorkspaceId = selectedWorkspaceId ?? roster.workspace_id;
  if (!portalWorkspaceId) {
    throw new Error("Workspace deliverables are unavailable for this session");
  }
  if (
    selectedWorkspaceId &&
    roster.workspace_id &&
    roster.workspace_id !== selectedWorkspaceId
  ) {
    throw new Error(
      "Active workspace changed while loading deliverables; please retry",
    );
  }
  const results = await Promise.all(
    PORTAL_ACTIVE_QUERY_STATES.map((state) =>
      fetchActiveStateThreads(portalWorkspaceId, state, signal),
    ),
  );
  const seen = new Set<string>();
  const activeThreads: PortalDeliverable[] = [];
  let hasMore = false;
  for (const res of results) {
    if (res.hasMore) {
      hasMore = true;
    }
    for (const thread of res.threads) {
      if (!ACTIVE_DELIVERABLE_STATES.has(thread.state) || seen.has(thread.id)) {
        continue;
      }
      seen.add(thread.id);
      activeThreads.push(thread);
    }
  }
  return {
    items: activeThreads.slice(0, 8),
    activeCount: activeThreads.length,
    hasMore,
  };
}

export function ControlPanelPage() {
  useEffect(() => {
    document.title = "Control Panel | MomoBot";
  }, []);

  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody className={pageStyles.page}>
        <ControlPanelBody />
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}

export function ControlPanelBody() {
  const { user } = useAuth();
  const isClient = useIsClient();
  const { agents, isLoading: agentsLoading } = useAgents();
  const {
    data: workspaceData,
    isLoading: workspaceLoading,
    error: workspaceError,
  } = useWorkspaceSelection();
  const [activeTab, setActiveTab] = useState("kickoff");
  const selectedWorkspaceId = workspaceData?.active_workspace_id ?? null;

  const activeWorkspaceName = useMemo(() => {
    if (!workspaceData) {
      return null;
    }
    const active = workspaceData.workspaces.find(
      (item) => item.id === workspaceData.active_workspace_id,
    );
    return active?.name ?? workspaceData.private_workspace_name ?? null;
  }, [workspaceData]);

  const scopeKey = useMemo(() => {
    if (workspaceLoading) {
      return null;
    }
    const workspacePart = workspaceData?.active_workspace_id;
    if (
      user &&
      !isStaticWebsiteOnly() &&
      !workspacePart &&
      workspaceError === null
    ) {
      return null;
    }
    const userPart = user?.id ?? "guest";
    return `${userPart}.${workspacePart ?? "default"}`;
  }, [
    user,
    workspaceData?.active_workspace_id,
    workspaceError,
    workspaceLoading,
  ]);
  const scopeReady = scopeKey !== null;

  const [checklist, setChecklist] = useState<Record<string, boolean>>(() =>
    scopeKey ? readChecklistState(scopeKey) : {},
  );
  const [academyProgress, setAcademyProgress] = useState<
    Record<string, boolean>
  >(() => (scopeKey ? readStartHereProgress(scopeKey) : {}));
  const [actionItems, setActionItems] = useState<LocalActionItem[]>(() =>
    scopeKey ? readActionItems(scopeKey) : [],
  );
  const [newActionText, setNewActionText] = useState("");

  useEffect(() => {
    if (!scopeKey) {
      setChecklist({});
      setAcademyProgress({});
      setActionItems([]);
      return;
    }
    setChecklist(readChecklistState(scopeKey));
    setAcademyProgress(readStartHereProgress(scopeKey));
    setActionItems(readActionItems(scopeKey));
  }, [scopeKey]);

  const deliverablesQuery = useQuery({
    queryKey: ["control-panel-deliverables", user?.id, selectedWorkspaceId],
    enabled: Boolean(user) && !isStaticWebsiteOnly() && !workspaceLoading,
    queryFn: ({ signal }) =>
      fetchPortalDeliverables(selectedWorkspaceId, signal),
    retry: false,
    staleTime: 30_000,
  });

  const hasCheckedReportingStatus = REPORTING_CONNECTIONS.every(
    (conn) => conn.status !== "unknown",
  );
  const connectedReportingCount = REPORTING_CONNECTIONS.filter(
    (conn) => conn.status === "connected",
  ).length;

  const completedChecklistCount = DAY_ONE_CHECKLIST.filter(
    (item) => checklist[item.id],
  ).length;
  const checklistPercent = Math.round(
    (completedChecklistCount / DAY_ONE_CHECKLIST.length) * 100,
  );
  const ringOffset = RING_CIRCUMFERENCE * (1 - checklistPercent / 100);
  const profileComplete = Boolean(checklist["complete-profile"]);

  const completedLessonsCount = BUSINESS_OWNER_LESSONS.filter(
    (lesson) => academyProgress[lesson.id],
  ).length;
  const activeDeliverableCount = deliverablesQuery.data?.activeCount ?? 0;
  const activeDeliverablesHasMore = Boolean(deliverablesQuery.data?.hasMore);
  const activeDeliverableItems = deliverablesQuery.data?.items ?? [];

  const toggleChecklist = (id: string) => {
    if (!scopeKey) {
      return;
    }
    setChecklist((prev) => {
      const next = { ...prev, [id]: !prev[id] };
      writeChecklistState(scopeKey, next);
      return next;
    });
  };

  const addActionItem = (event: React.FormEvent) => {
    event.preventDefault();
    if (!scopeKey) {
      return;
    }
    const cleaned = newActionText.trim();
    if (!cleaned) {
      return;
    }
    const nextItem: LocalActionItem = {
      id:
        typeof crypto !== "undefined" && "randomUUID" in crypto
          ? crypto.randomUUID()
          : `${Date.now()}-${Math.random().toString(36).slice(2)}`,
      text: cleaned,
      done: false,
      createdAt: new Date().toISOString(),
    };
    setActionItems((prev) => {
      const next = [nextItem, ...prev];
      writeActionItems(scopeKey, next);
      return next;
    });
    setNewActionText("");
  };

  const toggleActionItem = (id: string) => {
    if (!scopeKey) {
      return;
    }
    setActionItems((prev) => {
      const next = prev.map((item) =>
        item.id === id ? { ...item, done: !item.done } : item,
      );
      writeActionItems(scopeKey, next);
      return next;
    });
  };

  const removeActionItem = (id: string) => {
    if (!scopeKey) {
      return;
    }
    setActionItems((prev) => {
      const next = prev.filter((item) => item.id !== id);
      writeActionItems(scopeKey, next);
      return next;
    });
  };

  const openChatHref = buildChatPromptHref({
    isClient,
    agents,
    agentsLoading,
    prompt: "",
  });

  return (
    <main className={styles.frame} data-testid="client-control-panel">
      <header className={styles.hero}>
        <div className={styles.heroLead}>
          <div
            className={styles.progressRingWrap}
            aria-label={`Kickoff setup ${checklistPercent} percent complete`}
          >
            <svg
              className={styles.progressRingSvg}
              viewBox="0 0 64 64"
              aria-hidden="true"
            >
              <circle
                cx="32"
                cy="32"
                r={RING_RADIUS}
                fill="none"
                stroke="#4A5C50"
                strokeWidth="6"
              />
              <circle
                cx="32"
                cy="32"
                r={RING_RADIUS}
                fill="none"
                stroke="#D4F33B"
                strokeWidth="6"
                strokeLinecap="round"
                strokeDasharray={RING_CIRCUMFERENCE}
                strokeDashoffset={ringOffset}
                transform="rotate(-90 32 32)"
              />
            </svg>
            <span className={styles.progressRingLabel}>
              {checklistPercent}%
            </span>
          </div>

          <div className="min-w-0">
            <p className={styles.heroEyebrow}>
              <span className={styles.heroDot} aria-hidden="true" />
              <span>{activeWorkspaceName ?? "Workspace Control Panel"}</span>
            </p>
            <h1 className={styles.heroTitle}>Control Panel</h1>
            <p className={styles.heroLede}>
              Your workspace home for kickoff progress, weekly deliverables,
              meeting action plans, and reporting connections. Use Chat whenever
              you want MomoBot to create or revise an asset.
            </p>
          </div>
        </div>

        <div className={styles.heroActions}>
          <Button
            asChild
            variant="outline"
            size="sm"
            className={styles.heroBtnSecondary}
          >
            <Link href="/workspace/start-here">
              <GraduationCapIcon className="size-4" />
              Start Here / Academy
            </Link>
          </Button>
          <Button asChild size="sm" className={styles.heroBtnPrimary}>
            <Link href={openChatHref}>
              <MessageSquarePlusIcon className="size-4" />
              Open Chat
            </Link>
          </Button>
        </div>
      </header>

      <section
        className={styles.summaryStrip}
        aria-label="Workspace readiness summary"
        data-testid="control-panel-summary"
      >
        <div className={styles.summaryTile}>
          <span className={styles.summaryLabel}>Kickoff Setup</span>
          <span className={styles.summaryValue}>
            {completedChecklistCount} / {DAY_ONE_CHECKLIST.length}
          </span>
          <span className={styles.summaryMeta}>
            {profileComplete
              ? "Business Profile marked complete"
              : "Start with your Day-1 checklist"}
          </span>
        </div>

        <div className={styles.summaryTile}>
          <span className={styles.summaryLabel}>Active Deliverables</span>
          <span className={styles.summaryValue}>
            {deliverablesQuery.isLoading || workspaceLoading
              ? "Checking..."
              : deliverablesQuery.isError
                ? "Unavailable"
                : activeDeliverableCount === 0
                  ? "None queued"
                  : `${activeDeliverableCount}${activeDeliverablesHasMore ? "+" : ""} active`}
          </span>
          {deliverablesQuery.isError ? (
            <button
              type="button"
              className={styles.summaryLink}
              onClick={() => void deliverablesQuery.refetch()}
            >
              Retry loading deliverables
              <ArrowRightIcon className="size-3.5" />
            </button>
          ) : (
            <Link href="/workspace/inbox" className={styles.summaryLink}>
              Open Client Inbox
              <ArrowRightIcon className="size-3.5" />
            </Link>
          )}
        </div>

        <div className={styles.summaryTile}>
          <span className={styles.summaryLabel}>Tutorial &amp; Academy</span>
          <span className={styles.summaryValue}>
            {completedLessonsCount} / {BUSINESS_OWNER_LESSONS.length} lessons
          </span>
          <Link href="/workspace/start-here" className={styles.summaryLink}>
            Open Start Here / Academy
            <ArrowRightIcon className="size-3.5" />
          </Link>
        </div>

        <div className={styles.summaryTile}>
          <span className={styles.summaryLabel}>Reporting Access</span>
          <span className={styles.summaryValue}>
            {hasCheckedReportingStatus
              ? `${connectedReportingCount} / ${REPORTING_CONNECTIONS.length} connected`
              : "Status unknown"}
          </span>
          <button
            type="button"
            className={styles.summaryLink}
            onClick={() => setActiveTab("reporting")}
          >
            {hasCheckedReportingStatus
              ? "Review connection status"
              : `Review ${REPORTING_CONNECTIONS.length} supported channels`}
            <ArrowRightIcon className="size-3.5" />
          </button>
        </div>
      </section>

      <section
        className={styles.sectionShell}
        aria-labelledby="create-something-heading"
      >
        <div className={styles.sectionHeader}>
          <div>
            <p className={pageStyles.eyebrow}>1-Click Workflows</p>
            <h2 id="create-something-heading" className={styles.sectionHeading}>
              Create Something
            </h2>
          </div>
          <p className="text-muted-foreground text-xs">
            Pick a workflow to open a fresh chat pre-filled with a tailored
            prompt.
          </p>
        </div>

        <div className={styles.actionGrid} data-testid="create-something-grid">
          {CREATE_SOMETHING_CARDS.map((card) => {
            const href = buildChatPromptHref({
              isClient,
              agents,
              agentsLoading,
              prompt: card.prompt,
            });
            return (
              <article key={card.id} className={styles.actionCard}>
                <div className="space-y-2">
                  <div className="flex items-center justify-between gap-2">
                    <span className={styles.categoryChip}>{card.category}</span>
                    <SparklesIcon
                      className="size-4 shrink-0 text-[#1F7A66] dark:text-[#33A98F]"
                      aria-hidden="true"
                    />
                  </div>
                  <h3 className={styles.cardTitle}>{card.title}</h3>
                  <p className={styles.cardDesc}>{card.outcome}</p>
                  <p className={styles.promptPreview}>
                    &ldquo;{card.prompt.slice(0, 118)}...&rdquo;
                  </p>
                </div>
                <div className="pt-1">
                  <Button
                    asChild
                    size="sm"
                    variant="outline"
                    className={cn(
                      styles.brandActionBtn,
                      "w-full justify-between",
                    )}
                  >
                    <Link href={href}>
                      <span>Start in Chat</span>
                      <ArrowRightIcon className="size-3.5" />
                    </Link>
                  </Button>
                </div>
              </article>
            );
          })}
        </div>
      </section>

      <section aria-label="Workspace sections">
        <Tabs value={activeTab} onValueChange={setActiveTab} className="gap-4">
          <TabsList className={styles.tabsList}>
            <TabsTrigger value="kickoff" className={styles.tabTrigger}>
              Kickoff &amp; Roadmap
            </TabsTrigger>
            <TabsTrigger value="weekly" className={styles.tabTrigger}>
              Weekly Plan &amp; Approvals
            </TabsTrigger>
            <TabsTrigger value="meetings" className={styles.tabTrigger}>
              Meetings &amp; Action Plans
            </TabsTrigger>
            <TabsTrigger value="reporting" className={styles.tabTrigger}>
              Results &amp; Reporting
            </TabsTrigger>
          </TabsList>

          <TabsContent value="kickoff" className="space-y-4">
            <div className={styles.panelGrid}>
              <div className={styles.sheetCard}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <p className={pageStyles.eyebrow}>Guided Day-1 Setup</p>
                    <h2 className="mt-0.5 text-lg font-bold">
                      Setup Checklist
                    </h2>
                  </div>
                  <span
                    className={cn(
                      pageStyles.figure,
                      "text-muted-foreground text-xs font-semibold",
                    )}
                  >
                    {completedChecklistCount} of {DAY_ONE_CHECKLIST.length} done
                  </span>
                </div>
                <Progress
                  value={checklistPercent}
                  className="mt-3 mb-4"
                  aria-label="Day-1 setup progress"
                  aria-valuetext={`${completedChecklistCount} of ${DAY_ONE_CHECKLIST.length} complete`}
                />
                <ul className="divide-y">
                  {DAY_ONE_CHECKLIST.map((item) => {
                    const checked = Boolean(checklist[item.id]);
                    return (
                      <li key={item.id} className={styles.checklistRow}>
                        <div className="flex min-w-0 flex-1 items-start gap-2.5">
                          <button
                            type="button"
                            role="checkbox"
                            aria-checked={checked}
                            aria-label={item.title}
                            disabled={!scopeReady}
                            onClick={() => toggleChecklist(item.id)}
                            className={styles.checkButton}
                          >
                            {checked ? (
                              <CheckCircle2Icon className="size-4" />
                            ) : (
                              <CircleIcon className="text-muted-foreground size-4" />
                            )}
                          </button>
                          <div className="min-w-0">
                            <p
                              className={cn(
                                "text-sm font-semibold",
                                checked && "text-muted-foreground line-through",
                              )}
                            >
                              {item.title}
                            </p>
                            <p className="text-muted-foreground text-xs leading-relaxed">
                              {item.description}
                            </p>
                          </div>
                        </div>
                        <div className="shrink-0">
                          {item.actionKind === "prompt" ? (
                            <Button asChild size="sm" variant="ghost">
                              <Link
                                href={buildChatPromptHref({
                                  isClient,
                                  agents,
                                  agentsLoading,
                                  prompt: item.actionTarget,
                                })}
                              >
                                {item.actionLabel}
                              </Link>
                            </Button>
                          ) : item.actionTarget === "#reporting" ? (
                            <Button
                              type="button"
                              size="sm"
                              variant="ghost"
                              onClick={() => setActiveTab("reporting")}
                            >
                              {item.actionLabel}
                            </Button>
                          ) : (
                            <Button asChild size="sm" variant="ghost">
                              <Link href={item.actionTarget}>
                                {item.actionLabel}
                              </Link>
                            </Button>
                          )}
                        </div>
                      </li>
                    );
                  })}
                </ul>
              </div>

              <div className="space-y-4">
                <div className={styles.sheetCard}>
                  <div className="flex items-center justify-between gap-2">
                    <p className={pageStyles.eyebrow}>Business Context</p>
                    <StatusTag tone={profileComplete ? "ok" : "attention"}>
                      {profileComplete ? "Profile captured" : "Needs profile"}
                    </StatusTag>
                  </div>
                  <h2 className="mt-1 text-lg font-bold">
                    Business Profile Status
                  </h2>
                  <p className="text-muted-foreground mt-1.5 text-sm leading-relaxed">
                    {profileComplete
                      ? "Your Day-1 profile step is marked complete. Update it anytime in Chat when your offers or service area change."
                      : "Start with a 3-minute guided interview so MomoBot knows your services, local market, tone, and goals."}
                  </p>
                  <div className="mt-3">
                    <Button
                      asChild
                      size="sm"
                      variant="outline"
                      className={styles.brandActionBtn}
                    >
                      <Link
                        href={buildChatPromptHref({
                          isClient,
                          agents,
                          agentsLoading,
                          prompt: CREATE_SOMETHING_CARDS[5]!.prompt,
                        })}
                      >
                        <ClipboardCheckIcon className="size-4" />
                        Fill Out My Business Profile
                      </Link>
                    </Button>
                  </div>
                </div>

                <div className={styles.sheetCard}>
                  <div className="flex items-center gap-2">
                    <UsersIcon
                      className="text-muted-foreground size-4"
                      aria-hidden="true"
                    />
                    <p className={pageStyles.eyebrow}>Who&apos;s Doing What</p>
                  </div>
                  <h2 className="mt-1 text-lg font-bold">
                    Workspace Team Roles
                  </h2>
                  <dl className="mt-3 space-y-3">
                    {WORKSPACE_TEAM_ROLES.map((entry) => (
                      <div
                        key={entry.role}
                        className="border-t pt-2.5 first:border-t-0 first:pt-0"
                      >
                        <dt className="flex items-baseline justify-between gap-2 text-sm font-semibold">
                          <span>{entry.role}</span>
                          <span className="text-muted-foreground text-xs font-normal">
                            {entry.owner}
                          </span>
                        </dt>
                        <dd className="text-muted-foreground mt-0.5 text-xs leading-relaxed">
                          {entry.responsibilities}
                        </dd>
                      </div>
                    ))}
                  </dl>
                </div>
              </div>
            </div>

            <div className={styles.sheetCard}>
              <p className={pageStyles.eyebrow}>Growth Sequence</p>
              <h2 className="mt-0.5 text-lg font-bold">Phase Roadmap</h2>
              <div className={cn(styles.roadmapGrid, "mt-3")}>
                {KICKOFF_ROADMAP_PHASES.map((phase) => (
                  <div key={phase.id} className={styles.roadmapCard}>
                    <span className={styles.categoryChip}>{phase.phase}</span>
                    <h3 className="mt-2 text-sm font-bold">{phase.title}</h3>
                    <p className="text-muted-foreground mt-1 text-xs leading-relaxed">
                      {phase.summary}
                    </p>
                    <ul className="text-muted-foreground mt-2.5 list-disc space-y-1 pl-4 text-xs">
                      {phase.deliverables.map((item) => (
                        <li key={item}>{item}</li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            </div>
          </TabsContent>

          <TabsContent value="weekly" className="space-y-4">
            <div className={styles.panelGrid}>
              <div className={styles.sheetCard}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <p className={pageStyles.eyebrow}>Active Deliverables</p>
                    <h2 className="mt-0.5 text-lg font-bold">
                      Weekly Plan &amp; Requests
                    </h2>
                  </div>
                  <Button asChild size="sm" variant="outline">
                    <Link href="/workspace/inbox">
                      <InboxIcon className="size-4" />
                      Open Client Inbox
                    </Link>
                  </Button>
                </div>

                {deliverablesQuery.isLoading || workspaceLoading ? (
                  <p className="text-muted-foreground mt-4 text-sm">
                    Checking active workspace deliverables...
                  </p>
                ) : deliverablesQuery.isError ? (
                  <div
                    className={styles.emptySurface}
                    role="alert"
                    data-testid="deliverables-error-state"
                  >
                    <p className="text-sm font-semibold">
                      Unable to load active deliverables
                    </p>
                    <p className="text-muted-foreground mt-1 text-xs leading-relaxed">
                      We could not verify your active deliverables or pending
                      approvals for this workspace. Retry or open Client Inbox
                      directly.
                    </p>
                    <div className="mt-3 flex flex-wrap gap-2">
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        className={styles.brandActionBtn}
                        onClick={() => void deliverablesQuery.refetch()}
                      >
                        Retry
                      </Button>
                      <Button asChild size="sm" variant="ghost">
                        <Link href="/workspace/inbox">Go to Client Inbox</Link>
                      </Button>
                    </div>
                  </div>
                ) : activeDeliverableItems.length > 0 ? (
                  <ul className="mt-4 divide-y">
                    {activeDeliverableItems.map((item) => {
                      const badge = DELIVERABLE_STATE_LABELS[item.state] ?? {
                        label: item.state,
                        tone: "idle" as const,
                      };
                      return (
                        <li
                          key={item.id}
                          className="flex flex-wrap items-center justify-between gap-2 py-3"
                        >
                          <span className="text-sm font-medium">
                            {item.subject}
                          </span>
                          <StatusTag tone={badge.tone}>{badge.label}</StatusTag>
                        </li>
                      );
                    })}
                  </ul>
                ) : (
                  <div className={styles.emptySurface}>
                    <p className="text-sm font-semibold">
                      No active deliverables queued yet
                    </p>
                    <p className="text-muted-foreground mt-1 text-xs leading-relaxed">
                      Kick off your weekly GBP and social pack, a local SEO/AEO
                      article, or a new landing page from Create Something
                      above, or open Client Inbox to submit a request.
                    </p>
                    <div className="mt-3 flex flex-wrap gap-2">
                      <Button
                        asChild
                        size="sm"
                        variant="outline"
                        className={styles.brandActionBtn}
                      >
                        <Link
                          href={buildChatPromptHref({
                            isClient,
                            agents,
                            agentsLoading,
                            prompt: CREATE_SOMETHING_CARDS[2]!.prompt,
                          })}
                        >
                          Draft Weekly GBP &amp; Social Pack
                        </Link>
                      </Button>
                      <Button asChild size="sm" variant="ghost">
                        <Link href="/workspace/inbox">Go to Client Inbox</Link>
                      </Button>
                    </div>
                  </div>
                )}
              </div>

              <div className={styles.sheetCard}>
                <p className={pageStyles.eyebrow}>Approvals &amp; Cadence</p>
                <h2 className="mt-0.5 text-lg font-bold">
                  Review Before Publishing
                </h2>
                <p className="text-muted-foreground mt-1.5 text-sm leading-relaxed">
                  Nothing publishes to your live site, ads, or social channels
                  without explicit approval. Use these shortcuts to review
                  drafts and recurring schedules.
                </p>
                <div className="mt-4 flex flex-col gap-2">
                  <Button asChild variant="outline" className="justify-between">
                    <Link href="/workspace/inbox">
                      <span className="inline-flex items-center gap-2">
                        <InboxIcon className="size-4" />
                        Client Inbox &amp; Deliverable Review
                      </span>
                      <ArrowRightIcon className="size-4" />
                    </Link>
                  </Button>
                  {!isClient && (
                    <>
                      <Button
                        asChild
                        variant="outline"
                        className="justify-between"
                      >
                        <Link href="/workspace/approvals">
                          <span className="inline-flex items-center gap-2">
                            <ShieldCheckIcon className="size-4" />
                            Approvals Queue
                          </span>
                          <ArrowRightIcon className="size-4" />
                        </Link>
                      </Button>
                      <Button
                        asChild
                        variant="outline"
                        className="justify-between"
                      >
                        <Link href="/workspace/scheduled-tasks">
                          <span className="inline-flex items-center gap-2">
                            <CalendarClockIcon className="size-4" />
                            Scheduled Tasks
                          </span>
                          <ArrowRightIcon className="size-4" />
                        </Link>
                      </Button>
                    </>
                  )}
                </div>
              </div>
            </div>
          </TabsContent>

          <TabsContent value="meetings" className="space-y-4">
            <div className={styles.panelGrid}>
              <div className={styles.sheetCard}>
                <div className="flex items-center justify-between gap-2">
                  <div>
                    <p className={pageStyles.eyebrow}>Call Recaps</p>
                    <h2 className="mt-0.5 text-lg font-bold">
                      Meetings &amp; Call Notes
                    </h2>
                  </div>
                  <StatusTag tone="idle">Not connected</StatusTag>
                </div>
                <div
                  className={styles.emptySurface}
                  data-testid="meetings-empty-state"
                >
                  <div className="flex items-start gap-3">
                    <FileTextIcon
                      className="text-muted-foreground mt-0.5 size-5 shrink-0"
                      aria-hidden="true"
                    />
                    <div>
                      <p className="text-sm font-semibold">
                        Connect Fireflies or upload call notes
                      </p>
                      <p className="text-muted-foreground mt-1 text-xs leading-relaxed">
                        No meeting transcripts are connected yet. Paste or
                        upload notes from your kickoff or weekly sync in Chat to
                        generate a structured recap and owner action plan.
                      </p>
                      <div className="mt-3">
                        <Button
                          asChild
                          size="sm"
                          variant="outline"
                          className={styles.brandActionBtn}
                        >
                          <Link
                            href={buildChatPromptHref({
                              isClient,
                              agents,
                              agentsLoading,
                              prompt: MEETING_NOTES_PROMPT,
                            })}
                          >
                            Upload or paste call notes in Chat
                          </Link>
                        </Button>
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <div className={styles.sheetCard}>
                <p className={pageStyles.eyebrow}>Follow-Through</p>
                <h2 className="mt-0.5 text-lg font-bold">Open Action Items</h2>
                <p className="text-muted-foreground mt-1 text-xs leading-relaxed">
                  Track real follow-ups from your calls right here. Items save
                  locally in your browser for this workspace.
                </p>
                <form
                  onSubmit={addActionItem}
                  className="mt-3 flex items-center gap-2"
                >
                  <Input
                    aria-label="Add an action item"
                    placeholder={
                      scopeReady
                        ? "Add an action item..."
                        : "Loading workspace..."
                    }
                    disabled={!scopeReady}
                    value={newActionText}
                    onChange={(event) => setNewActionText(event.target.value)}
                  />
                  <Button
                    type="submit"
                    size="sm"
                    variant="outline"
                    disabled={!scopeReady}
                  >
                    <PlusIcon className="size-4" />
                    Add
                  </Button>
                </form>

                {actionItems.length === 0 ? (
                  <p className="text-muted-foreground mt-4 text-xs">
                    No action items logged yet.
                  </p>
                ) : (
                  <ul className="mt-3 divide-y">
                    {actionItems.map((item) => (
                      <li
                        key={item.id}
                        className="flex items-center justify-between gap-2 py-2.5"
                      >
                        <button
                          type="button"
                          onClick={() => toggleActionItem(item.id)}
                          className="flex min-w-0 flex-1 items-center gap-2 text-left text-sm"
                        >
                          {item.done ? (
                            <CheckCircle2Icon className="size-4 shrink-0 text-[#1F7A66] dark:text-[#33A98F]" />
                          ) : (
                            <CircleIcon className="text-muted-foreground size-4 shrink-0" />
                          )}
                          <span
                            className={cn(
                              "truncate",
                              item.done && "text-muted-foreground line-through",
                            )}
                          >
                            {item.text}
                          </span>
                        </button>
                        <Button
                          type="button"
                          size="icon-sm"
                          variant="ghost"
                          aria-label={`Remove ${item.text}`}
                          onClick={() => removeActionItem(item.id)}
                        >
                          <Trash2Icon className="size-3.5" />
                        </Button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          </TabsContent>

          <TabsContent value="reporting" className="space-y-4">
            <div className={styles.sheetCard}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className={pageStyles.eyebrow}>Lead &amp; Channel Proof</p>
                  <h2 className="mt-0.5 text-lg font-bold">
                    Results &amp; Reporting
                  </h2>
                  <p className="text-muted-foreground mt-1 max-w-2xl text-sm leading-relaxed">
                    Supported reporting and publishing channels for this
                    workspace. Live connection status is not checked on this
                    page yet, and no placeholder or estimated KPI numbers are
                    shown before real data is linked.
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  {!isClient ? (
                    <Button asChild size="sm" className={styles.heroBtnPrimary}>
                      <Link href="/workspace/reports">
                        <BarChart3Icon className="size-4" />
                        Open Reports &amp; Leads
                      </Link>
                    </Button>
                  ) : (
                    <Button asChild size="sm" className={styles.heroBtnPrimary}>
                      <Link href="/workspace/inbox">
                        <BarChart3Icon className="size-4" />
                        Open Client Inbox
                      </Link>
                    </Button>
                  )}
                  <Button
                    asChild
                    size="sm"
                    variant="outline"
                    className={styles.brandActionBtn}
                  >
                    <Link
                      href={buildChatPromptHref({
                        isClient,
                        agents,
                        agentsLoading,
                        prompt: CONNECT_REPORTING_PROMPT,
                      })}
                    >
                      Get connection checklist
                    </Link>
                  </Button>
                </div>
              </div>

              <div
                className={cn(styles.connectionGrid, "mt-5")}
                data-testid="reporting-connections-grid"
              >
                {REPORTING_CONNECTIONS.map((conn) => (
                  <div key={conn.id} className={styles.connectionPill}>
                    <div className="flex items-center justify-between gap-2">
                      <div>
                        <p className="text-sm font-bold">{conn.name}</p>
                        <p className="text-muted-foreground text-xs">
                          {conn.category}
                        </p>
                      </div>
                      <StatusTag tone="idle">{conn.statusLabel}</StatusTag>
                    </div>
                    <p className="text-muted-foreground text-xs leading-relaxed">
                      {conn.unlocks}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          </TabsContent>
        </Tabs>
      </section>
    </main>
  );
}
