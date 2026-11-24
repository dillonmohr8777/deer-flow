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

async function fetchPortalDeliverables(
  signal?: AbortSignal,
): Promise<PortalDeliverable[]> {
  const rosterRes = await apiFetch(
    `${getBackendBaseURL()}/api/client-portal/clients`,
    { signal, cache: "no-store" },
  );
  if (!rosterRes.ok) {
    return [];
  }
  const roster = (await rosterRes.json()) as PortalRoster;
  if (!roster.workspace_id) {
    return [];
  }
  const listRes = await apiFetch(
    `${getBackendBaseURL()}/api/client-portal/threads?state=all&limit=8&offset=0`,
    {
      signal,
      cache: "no-store",
      headers: { "X-Portal-Workspace": roster.workspace_id },
    },
  );
  if (!listRes.ok) {
    return [];
  }
  const data = (await listRes.json()) as { threads?: PortalDeliverable[] };
  return Array.isArray(data.threads) ? data.threads : [];
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
  const { agents } = useAgents();
  const { data: workspaceData } = useWorkspaceSelection();
  const [activeTab, setActiveTab] = useState("kickoff");

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
    const userPart = user?.id ?? "guest";
    const workspacePart = workspaceData?.active_workspace_id ?? "default";
    return `${userPart}.${workspacePart}`;
  }, [user?.id, workspaceData?.active_workspace_id]);

  const [checklist, setChecklist] = useState<Record<string, boolean>>(() =>
    readChecklistState(scopeKey),
  );
  const [academyProgress, setAcademyProgress] = useState<
    Record<string, boolean>
  >(() => readStartHereProgress(scopeKey));
  const [actionItems, setActionItems] = useState<LocalActionItem[]>(() =>
    readActionItems(scopeKey),
  );
  const [newActionText, setNewActionText] = useState("");

  useEffect(() => {
    setChecklist(readChecklistState(scopeKey));
    setAcademyProgress(readStartHereProgress(scopeKey));
    setActionItems(readActionItems(scopeKey));
  }, [scopeKey]);

  const deliverablesQuery = useQuery({
    queryKey: [
      "control-panel-deliverables",
      user?.id,
      workspaceData?.active_workspace_id,
    ],
    enabled: Boolean(user) && !isStaticWebsiteOnly(),
    queryFn: ({ signal }) => fetchPortalDeliverables(signal),
    retry: false,
    staleTime: 30_000,
  });

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
  const activeDeliverableCount = deliverablesQuery.data?.length ?? 0;

  const toggleChecklist = (id: string) => {
    setChecklist((prev) => {
      const next = { ...prev, [id]: !prev[id] };
      writeChecklistState(scopeKey, next);
      return next;
    });
  };

  const addActionItem = (event: React.FormEvent) => {
    event.preventDefault();
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
    setActionItems((prev) => {
      const next = prev.map((item) =>
        item.id === id ? { ...item, done: !item.done } : item,
      );
      writeActionItems(scopeKey, next);
      return next;
    });
  };

  const removeActionItem = (id: string) => {
    setActionItems((prev) => {
      const next = prev.filter((item) => item.id !== id);
      writeActionItems(scopeKey, next);
      return next;
    });
  };

  const openChatHref = buildChatPromptHref({
    isClient,
    agents,
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
            {deliverablesQuery.isLoading
              ? "Checking..."
              : activeDeliverableCount === 0
                ? "None queued"
                : `${activeDeliverableCount} active`}
          </span>
          <Link href="/workspace/inbox" className={styles.summaryLink}>
            Open Client Inbox
            <ArrowRightIcon className="size-3.5" />
          </Link>
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
            {REPORTING_CONNECTIONS.length} channels ready
          </span>
          <button
            type="button"
            className={styles.summaryLink}
            onClick={() => setActiveTab("reporting")}
          >
            Review connection status
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

                {deliverablesQuery.isLoading ? (
                  <p className="text-muted-foreground mt-4 text-sm">
                    Checking active workspace deliverables...
                  </p>
                ) : deliverablesQuery.data &&
                  deliverablesQuery.data.length > 0 ? (
                  <ul className="mt-4 divide-y">
                    {deliverablesQuery.data.map((item) => {
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
                    placeholder="Add an action item..."
                    value={newActionText}
                    onChange={(event) => setNewActionText(event.target.value)}
                  />
                  <Button type="submit" size="sm" variant="outline">
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
                    Live spend, traffic, and lead match-back metrics appear once
                    your channels are connected. No placeholder or estimated KPI
                    numbers are shown before real data is linked.
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button asChild size="sm" className={styles.heroBtnPrimary}>
                    <Link href="/workspace/reports">
                      <BarChart3Icon className="size-4" />
                      Open Reports &amp; Leads
                    </Link>
                  </Button>
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
