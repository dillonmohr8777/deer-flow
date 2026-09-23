"use client";

import { useQuery } from "@tanstack/react-query";
import { CopyIcon, TriangleAlertIcon } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  EmptyState,
  ErrorState,
  FilterGroup,
  pageStyles,
  StatusTag,
  type StatusTone,
  WorkingState,
} from "@/components/workspace/page-body";
import {
  ScheduledTaskScheduleInput,
  type ScheduleValue,
} from "@/components/workspace/scheduled-task-schedule-input";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { listAgents } from "@/core/agents/api";
import { useAgentsApiEnabled } from "@/core/agents/hooks";
import { useI18n } from "@/core/i18n/hooks";
import { hasScheduleSpec } from "@/core/scheduled-tasks/cron";
import {
  useCreateScheduledTask,
  useUpdateScheduledTask,
  useDeleteScheduledTask,
  usePauseScheduledTask,
  useResumeScheduledTask,
  useScheduledTasks,
  useTriggerScheduledTask,
  useThreadScheduledTasks,
} from "@/core/scheduled-tasks/hooks";
import { RECIPES, type Recipe } from "@/core/scheduled-tasks/recipes";
import { useScheduledTaskRunHistory } from "@/core/scheduled-tasks/run-history";
import { matchesScheduledTaskQuery } from "@/core/scheduled-tasks/search";
import type {
  ScheduledTask,
  ScheduledTaskRun,
} from "@/core/scheduled-tasks/types";
import { cn } from "@/lib/utils";

function ReuseThreadNotice({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <Alert className="border-amber-500/50 bg-amber-500/10">
      <TriangleAlertIcon className="text-amber-600 dark:text-amber-400" />
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription>{description}</AlertDescription>
    </Alert>
  );
}

/** Absolute local time, or null when there is none; callers name the gap. */
function formatTimestamp(value: string | null, locale: string): string | null {
  if (!value) {
    return null;
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  // Use a locale-aware short format like "2026-07-03 09:00". Future timestamps
  // (next_run_at) render as an absolute time, not a relative "ago" string.
  const intlLocale = locale === "zh-CN" ? "zh-CN" : "en-US";
  return new Intl.DateTimeFormat(intlLocale, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

const DEFAULT_ASSISTANT_ID = "lead_agent";

/** Colour says state: working now, fine, stopped, or failed. */
function statusTone(status: string): StatusTone {
  if (status === "running") return "active";
  if (status === "enabled" || status === "completed") return "ok";
  if (status === "failed") return "danger";
  return "idle";
}

function agentDisplayName(
  assistantId: string | null | undefined,
  leadLabel: string,
): string {
  if (!assistantId || assistantId === DEFAULT_ASSISTANT_ID) {
    return leadLabel;
  }
  return assistantId;
}

export default function ScheduledTasksPage() {
  const { t, locale } = useI18n();
  const st = t.scheduledTasks;
  const searchParams = useSearchParams();
  const threadId = searchParams.get("thread_id");
  const allTasksQuery = useScheduledTasks();
  const threadTasksQuery = useThreadScheduledTasks(threadId);
  const { enabled: agentsApiEnabled, isLoading: agentsApiLoading } =
    useAgentsApiEnabled();
  const agentsQuery = useQuery({
    queryKey: ["agents"],
    queryFn: listAgents,
    enabled: !agentsApiLoading && agentsApiEnabled,
    retry: false,
  });
  const tasksQuery = threadId ? threadTasksQuery : allTasksQuery;
  const data = tasksQuery.data;
  const queryError = tasksQuery.error;
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [contextMode, setContextMode] = useState<
    "fresh_thread_per_run" | "reuse_thread"
  >(threadId ? "reuse_thread" : "fresh_thread_per_run");
  const [targetThreadId, setTargetThreadId] = useState(threadId ?? "");
  const [title, setTitle] = useState("");
  const [prompt, setPrompt] = useState("");
  const [createAssistantId, setCreateAssistantId] =
    useState(DEFAULT_ASSISTANT_ID);
  const [createSchedule, setCreateSchedule] = useState<ScheduleValue>({
    schedule_type: "cron",
    schedule_spec: { cron: "0 9 * * *" },
    timezone: "",
  });
  const [statusFilter, setStatusFilter] = useState<
    "all" | "enabled" | "paused" | "running" | "completed" | "failed"
  >("all");
  const [typeFilter, setTypeFilter] = useState<
    "all" | "once" | "cron" | "interval"
  >("all");
  const [taskSearch, setTaskSearch] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [editTaskId, setEditTaskId] = useState<string | undefined>(undefined);
  const [editTitle, setEditTitle] = useState("");
  const [editPrompt, setEditPrompt] = useState("");
  const [editAssistantId, setEditAssistantId] = useState(DEFAULT_ASSISTANT_ID);
  const [editSchedule, setEditSchedule] = useState<ScheduleValue>({
    schedule_type: "cron",
    schedule_spec: { cron: "0 9 * * *" },
    timezone: "UTC",
  });
  const [createNonce, setCreateNonce] = useState(0);
  const createFormRef = useRef<HTMLDivElement>(null);
  const createTitleRef = useRef<HTMLInputElement>(null);
  const agentOptions = useMemo(() => {
    const names = new Set((agentsQuery.data ?? []).map((agent) => agent.name));
    const options = [
      {
        value: DEFAULT_ASSISTANT_ID,
        label: st.create.leadAgent,
      },
      ...(agentsQuery.data ?? [])
        .filter((agent) => agent.name !== DEFAULT_ASSISTANT_ID)
        .map((agent) => ({ value: agent.name, label: agent.name })),
    ];
    for (const extra of [createAssistantId, editAssistantId]) {
      if (extra && extra !== DEFAULT_ASSISTANT_ID && !names.has(extra)) {
        options.push({ value: extra, label: extra });
        names.add(extra);
      }
    }
    return options;
  }, [
    agentsQuery.data,
    createAssistantId,
    editAssistantId,
    st.create.leadAgent,
  ]);
  const filteredData = (data ?? []).filter((task) => {
    const statusPass = statusFilter === "all" || task.status === statusFilter;
    const typePass = typeFilter === "all" || task.schedule_type === typeFilter;
    return (
      statusPass && typePass && matchesScheduledTaskQuery(task, taskSearch)
    );
  });
  const selectedTask =
    filteredData.find((task) => task.id === selectedTaskId) ?? filteredData[0];
  const taskRunsQuery = useScheduledTaskRunHistory(selectedTask?.id);
  const createTask = useCreateScheduledTask();
  const updateTask = useUpdateScheduledTask(selectedTask?.id ?? "");
  const pauseTask = usePauseScheduledTask();
  const resumeTask = useResumeScheduledTask();
  const triggerTask = useTriggerScheduledTask();
  const deleteTask = useDeleteScheduledTask();

  const scheduleTypeLabel = (v: string) =>
    v === "cron"
      ? st.scheduleType.cron
      : v === "once"
        ? st.scheduleType.once
        : v === "interval"
          ? st.scheduleType.interval
          : v;
  const statusLabel = (v: string) =>
    (st.status as Record<string, string>)[v] ?? v;
  const contextModeLabel = (v: string) =>
    v === "fresh_thread_per_run"
      ? st.context.fresh
      : v === "reuse_thread"
        ? st.context.reuse
        : v;
  const runTriggerLabel = (v: string) =>
    (st.runTrigger as Record<string, string>)[v] ?? v;
  const runStatusLabel = (v: string) =>
    (st.runStatus as Record<string, string>)[v] ?? v;
  const runSummary = (run: ScheduledTaskRun) =>
    `${runTriggerLabel(run.trigger)} · ${runStatusLabel(run.status)}`;
  const applyRecipe = (recipe: Recipe) => {
    const labels = st.recipes[recipe.titleKey];
    setTitle(labels.title);
    setPrompt(recipe.prompt);
    setCreateSchedule(recipe.schedule);
    setContextMode("fresh_thread_per_run");
    setCreateNonce((n) => n + 1);
  };
  const duplicateTask = (task: ScheduledTask) => {
    setTitle(`${task.title}${st.actions.duplicateTitleSuffix}`);
    setPrompt(task.prompt);
    setContextMode(task.context_mode);
    setTargetThreadId(task.thread_id ?? "");
    setCreateAssistantId(task.assistant_id ?? DEFAULT_ASSISTANT_ID);
    setCreateSchedule({
      schedule_type: task.schedule_type,
      schedule_spec: { ...task.schedule_spec },
      timezone: task.timezone,
    });
    setFormError(null);
    setCreateNonce((nonce) => nonce + 1);
    createFormRef.current?.scrollIntoView({
      behavior: "smooth",
      block: "start",
    });
    createTitleRef.current?.focus();
  };

  useEffect(() => {
    document.title = `${t.sidebar.scheduledTasks} - ${t.pages.appName}`;
  }, [t.pages.appName, t.sidebar.scheduledTasks]);

  useEffect(() => {
    if (!selectedTaskId) {
      return;
    }
    const stillVisible = filteredData.some(
      (task) => task.id === selectedTaskId,
    );
    if (!stillVisible) {
      setSelectedTaskId(filteredData[0]?.id ?? null);
      setEditing(false);
    }
  }, [filteredData, selectedTaskId]);

  // Reset before children commit so the keyed input captures this task.
  // Same-id refetches retain the in-progress draft.
  if (editTaskId !== selectedTask?.id) {
    setEditTaskId(selectedTask?.id);
    if (!selectedTask) {
      setEditing(false);
    } else {
      setEditTitle(selectedTask.title);
      setEditPrompt(selectedTask.prompt);
      setEditAssistantId(selectedTask.assistant_id ?? DEFAULT_ASSISTANT_ID);
      const spec = selectedTask.schedule_spec as {
        cron?: string;
        run_at?: string;
        every_seconds?: number;
      };
      setEditSchedule({
        schedule_type: selectedTask.schedule_type,
        schedule_spec: {
          cron: typeof spec.cron === "string" ? spec.cron : undefined,
          run_at: typeof spec.run_at === "string" ? spec.run_at : undefined,
          every_seconds:
            typeof spec.every_seconds === "number"
              ? spec.every_seconds
              : undefined,
        },
        timezone: selectedTask.timezone || "UTC",
      });
    }
  }

  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody className={pageStyles.page}>
        <div className="momentum-page mx-auto flex w-full max-w-(--container-width-lg) flex-col gap-6 p-4 pb-28 sm:p-6 sm:pb-28">
          <header className="pt-2">
            <h1 className="text-2xl">{t.sidebar.scheduledTasks}</h1>
            <p className={cn(pageStyles.lede, "mt-1")}>{st.lede}</p>
          </header>
          <section
            ref={createFormRef}
            className={cn(
              "grid gap-3 rounded-lg border p-4 sm:p-5",
              pageStyles.sheet,
            )}
            data-testid="scheduled-task-create-form"
            aria-labelledby="scheduled-task-create-title"
          >
            <h2
              id="scheduled-task-create-title"
              className="text-lg font-semibold"
            >
              {st.create.title}
            </h2>
            <div
              className="flex flex-wrap items-center gap-1.5"
              data-testid="schedule-recipes"
            >
              <span className={cn(pageStyles.eyebrow, "mr-1")}>
                {st.recipes.label}
              </span>
              {RECIPES.map((recipe) => (
                <Button
                  key={recipe.id}
                  variant="outline"
                  size="sm"
                  onClick={() => applyRecipe(recipe)}
                >
                  {st.recipes[recipe.titleKey].title}
                </Button>
              ))}
            </div>
            <FilterGroup
              label={st.detail.contextMode}
              showLabel
              value={contextMode}
              onChange={setContextMode}
              options={[
                { value: "fresh_thread_per_run", label: st.context.fresh },
                { value: "reuse_thread", label: st.context.reuse },
              ]}
            />
            {contextMode === "reuse_thread" && (
              <>
                <Input
                  value={targetThreadId}
                  onChange={(event) => setTargetThreadId(event.target.value)}
                  placeholder={st.context.threadIdPlaceholder}
                />
                <ReuseThreadNotice
                  title={st.context.reuseNoticeTitle}
                  description={st.context.reuseNoticeDescription}
                />
              </>
            )}
            <Select
              value={createAssistantId}
              onValueChange={setCreateAssistantId}
            >
              <SelectTrigger
                className="w-full"
                data-testid="scheduled-task-create-agent"
                aria-label={st.create.agent}
              >
                <SelectValue placeholder={st.create.agent} />
              </SelectTrigger>
              <SelectContent>
                {agentOptions.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Input
              ref={createTitleRef}
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder={st.create.taskTitle}
            />
            <Textarea
              rows={4}
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              placeholder={st.create.prompt}
            />
            <ScheduledTaskScheduleInput
              key={createNonce}
              initial={createSchedule}
              onChange={setCreateSchedule}
            />
            {formError && (
              <div className="text-destructive text-sm">{formError}</div>
            )}
            <Button
              onClick={() => {
                const hasSchedule = hasScheduleSpec(
                  createSchedule.schedule_spec,
                );
                if (
                  !title ||
                  !prompt ||
                  !hasSchedule ||
                  (contextMode === "reuse_thread" && !targetThreadId)
                ) {
                  setFormError(st.create.fillRequired);
                  return;
                }
                setFormError(null);
                createTask.mutate(
                  {
                    context_mode: contextMode,
                    thread_id:
                      contextMode === "reuse_thread" ? targetThreadId : null,
                    assistant_id: createAssistantId,
                    title,
                    prompt,
                    schedule_type: createSchedule.schedule_type,
                    schedule_spec: createSchedule.schedule_spec,
                    timezone: createSchedule.timezone || "UTC",
                  },
                  {
                    onSuccess: () => {
                      // Clear the form so a follow-up task starts fresh.
                      setTitle("");
                      setPrompt("");
                      setTargetThreadId("");
                      setCreateAssistantId(DEFAULT_ASSISTANT_ID);
                      setContextMode("fresh_thread_per_run");
                      setCreateSchedule({
                        schedule_type: "cron",
                        schedule_spec: { cron: "0 9 * * *" },
                        timezone: "",
                      });
                      setCreateNonce((n) => n + 1);
                    },
                  },
                );
              }}
              disabled={
                !title ||
                !prompt ||
                !hasScheduleSpec(createSchedule.schedule_spec) ||
                (contextMode === "reuse_thread" && !targetThreadId) ||
                createTask.isPending
              }
            >
              {st.create.submit}
            </Button>
          </section>
          {threadId && (
            <div className="text-muted-foreground text-sm">
              {st.detail.filteredByThread.replace("{id}", threadId)}
            </div>
          )}
          {queryError ? (
            <div data-testid="scheduled-task-load-error">
              <ErrorState
                message={st.detail.loadFailed}
                detail={queryError.message}
                action={
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={tasksQuery.isFetching}
                    onClick={() => void tasksQuery.refetch()}
                  >
                    {t.common.tryAgain}
                  </Button>
                }
              />
            </div>
          ) : null}
          <div className="flex flex-col gap-3">
            <div className="flex gap-2">
              <Input
                type="search"
                aria-label={st.search.placeholder}
                placeholder={st.search.placeholder}
                value={taskSearch}
                onChange={(event) => setTaskSearch(event.target.value)}
              />
              {taskSearch && (
                <Button variant="outline" onClick={() => setTaskSearch("")}>
                  {st.search.clear}
                </Button>
              )}
            </div>
            <div className="flex flex-wrap gap-x-8 gap-y-2">
              <FilterGroup
                label={st.filters.status}
                showLabel
                value={statusFilter}
                onChange={setStatusFilter}
                options={[
                  { value: "all", label: st.filters.allStatuses },
                  { value: "enabled", label: st.filters.enabled },
                  { value: "paused", label: st.filters.paused },
                  { value: "completed", label: st.filters.completed },
                  { value: "failed", label: st.filters.failed },
                ]}
              />
              <FilterGroup
                label={st.filters.type}
                showLabel
                value={typeFilter}
                onChange={setTypeFilter}
                options={[
                  { value: "all", label: st.filters.allTypes },
                  { value: "cron", label: st.filters.cron },
                  { value: "once", label: st.filters.once },
                  { value: "interval", label: st.filters.interval },
                ]}
              />
            </div>
          </div>
          <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,24rem)]">
            <div data-testid="scheduled-task-list" className="flex flex-col">
              {tasksQuery.isLoading ? (
                <WorkingState label={t.common.loading} />
              ) : null}
              {data && !queryError && data.length === 0 && (
                <EmptyState momo="reliability">{st.empty}</EmptyState>
              )}
              {data &&
                !queryError &&
                data.length > 0 &&
                filteredData.length === 0 && (
                  <p
                    role="status"
                    data-testid="scheduled-task-search-empty"
                    className="text-muted-foreground py-4 text-sm"
                  >
                    {st.search.noResults}
                  </p>
                )}
              {filteredData.length > 0 && (
                <ul className={cn("divide-y border-y", pageStyles.rows)}>
                  {filteredData.map((task) => {
                    const isSelected = selectedTask?.id === task.id;
                    const nextRun = formatTimestamp(task.next_run_at, locale);
                    return (
                      <li
                        key={task.id}
                        className={cn(
                          pageStyles.pin,
                          task.status === "running" && "pinned",
                        )}
                      >
                        <button
                          type="button"
                          onClick={() => setSelectedTaskId(task.id)}
                          aria-pressed={isSelected}
                          data-testid={`scheduled-task-item-${task.id}`}
                          className={cn(
                            "flex w-full flex-col gap-1 border-l-2 px-3 py-3 text-left transition-colors",
                            isSelected
                              ? "border-l-primary bg-accent"
                              : "hover:bg-accent border-l-transparent",
                          )}
                        >
                          <span className="flex items-start justify-between gap-3">
                            <span className="min-w-0 font-bold [overflow-wrap:anywhere]">
                              {task.title}
                            </span>
                            <StatusTag
                              tone={statusTone(task.status)}
                              className="mt-0.5 shrink-0"
                            >
                              {statusLabel(task.status)}
                            </StatusTag>
                          </span>
                          <span className="text-muted-foreground text-xs">
                            {scheduleTypeLabel(task.schedule_type)}
                            {" · "}
                            {st.detail.nextRun}{" "}
                            {nextRun ?? st.detail.notScheduled}
                          </span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
            {/* No task, no detail sheet: the list already says why. */}
            {selectedTask ? (
              <section
                className={cn("rounded-lg border p-4 sm:p-5", pageStyles.sheet)}
                data-testid="scheduled-task-detail"
              >
                <div className="flex flex-col gap-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <h2 className="text-lg font-semibold [overflow-wrap:anywhere]">
                        {selectedTask.title}
                      </h2>
                      <StatusTag
                        tone={statusTone(selectedTask.status)}
                        className="mt-1"
                      >
                        {statusLabel(selectedTask.status)}
                      </StatusTag>
                    </div>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setEditing((value) => !value)}
                    >
                      {editing ? st.actions.cancelEdit : st.actions.edit}
                    </Button>
                  </div>
                  {/* Receipt fields: plain, and every gap named in words. */}
                  <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1.5 text-sm">
                    <dt className="text-muted-foreground">
                      {st.detail.schedule}
                    </dt>
                    <dd>{scheduleTypeLabel(selectedTask.schedule_type)}</dd>
                    <dt className="text-muted-foreground">
                      {st.detail.nextRun}
                    </dt>
                    <dd>
                      {formatTimestamp(selectedTask.next_run_at, locale) ??
                        st.detail.notScheduled}
                    </dd>
                    <dt className="text-muted-foreground">
                      {st.detail.lastRun}
                    </dt>
                    <dd>
                      {formatTimestamp(selectedTask.last_run_at, locale) ??
                        st.detail.never}
                    </dd>
                    <dt className="text-muted-foreground">{st.detail.agent}</dt>
                    <dd className="[overflow-wrap:anywhere]">
                      {agentDisplayName(
                        selectedTask.assistant_id,
                        st.create.leadAgent,
                      )}
                    </dd>
                    <dt className="text-muted-foreground">
                      {st.detail.contextMode}
                    </dt>
                    <dd>{contextModeLabel(selectedTask.context_mode)}</dd>
                    <dt className="text-muted-foreground">
                      {selectedTask.context_mode === "reuse_thread"
                        ? st.detail.thread
                        : st.detail.lastThread}
                    </dt>
                    <dd className="font-mono text-xs leading-5 break-all">
                      {(selectedTask.context_mode === "reuse_thread"
                        ? selectedTask.thread_id
                        : selectedTask.last_thread_id) ?? st.detail.none}
                    </dd>
                    <dt className="text-muted-foreground">
                      {st.detail.lastRunId}
                    </dt>
                    <dd className="font-mono text-xs leading-5 break-all">
                      {selectedTask.last_run_id ?? st.detail.none}
                    </dd>
                    <dt className="text-muted-foreground">
                      {st.detail.lastError}
                    </dt>
                    <dd
                      className={cn(
                        "[overflow-wrap:anywhere]",
                        selectedTask.last_error && "text-destructive",
                      )}
                    >
                      {selectedTask.last_error ?? st.detail.none}
                    </dd>
                  </dl>
                  {selectedTask.context_mode === "reuse_thread" && (
                    <ReuseThreadNotice
                      title={st.context.reuseNoticeTitle}
                      description={st.context.reuseNoticeDescription}
                    />
                  )}
                  {editing ? (
                    <div className="flex flex-col gap-2 rounded-lg border p-3">
                      <Input
                        value={editTitle}
                        onChange={(event) => setEditTitle(event.target.value)}
                        placeholder={st.edit.titlePlaceholder}
                      />
                      <Textarea
                        rows={4}
                        value={editPrompt}
                        onChange={(event) => setEditPrompt(event.target.value)}
                        placeholder={st.edit.promptPlaceholder}
                      />
                      <Select
                        value={editAssistantId}
                        onValueChange={setEditAssistantId}
                      >
                        <SelectTrigger
                          className="w-full"
                          data-testid="scheduled-task-edit-agent"
                          aria-label={st.create.agent}
                        >
                          <SelectValue placeholder={st.create.agent} />
                        </SelectTrigger>
                        <SelectContent>
                          {agentOptions.map((option) => (
                            <SelectItem key={option.value} value={option.value}>
                              {option.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <ScheduledTaskScheduleInput
                        key={selectedTask.id}
                        initial={editSchedule}
                        onChange={setEditSchedule}
                        scheduleTypeLocked
                      />
                      <Button
                        size="sm"
                        onClick={() => {
                          if (!hasScheduleSpec(editSchedule.schedule_spec))
                            return;
                          const pinned =
                            selectedTask.assistant_id ?? DEFAULT_ASSISTANT_ID;
                          updateTask.mutate({
                            title: editTitle,
                            prompt: editPrompt,
                            ...(editAssistantId !== pinned
                              ? { assistant_id: editAssistantId }
                              : {}),
                            schedule_spec: editSchedule.schedule_spec,
                            timezone: editSchedule.timezone || "UTC",
                          });
                        }}
                        disabled={
                          updateTask.isPending ||
                          !hasScheduleSpec(editSchedule.schedule_spec)
                        }
                      >
                        {st.edit.submit}
                      </Button>
                    </div>
                  ) : (
                    <p className="text-sm leading-6 [overflow-wrap:anywhere] whitespace-pre-wrap">
                      {selectedTask.prompt}
                    </p>
                  )}
                  <div className="flex flex-wrap gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() =>
                        selectedTask.status === "paused"
                          ? resumeTask.mutate(selectedTask.id)
                          : pauseTask.mutate(selectedTask.id)
                      }
                    >
                      {selectedTask.status === "paused"
                        ? st.actions.resume
                        : st.actions.pause}
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => triggerTask.mutate(selectedTask.id)}
                    >
                      {st.actions.trigger}
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => duplicateTask(selectedTask)}
                    >
                      <CopyIcon />
                      {st.actions.duplicate}
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      className="text-destructive hover:text-destructive"
                      onClick={() => setDeleteOpen(true)}
                    >
                      {st.actions.delete}
                    </Button>
                  </div>
                  <nav
                    aria-label={st.history.navigation}
                    className="flex flex-wrap items-center gap-2"
                  >
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={
                        taskRunsQuery.page === 0 || taskRunsQuery.isFetching
                      }
                      onClick={taskRunsQuery.newer}
                    >
                      {st.history.newer}
                    </Button>
                    <span className="text-muted-foreground text-sm">
                      {st.history.page.replace(
                        "{page}",
                        String(taskRunsQuery.page + 1),
                      )}
                    </span>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={
                        !taskRunsQuery.hasOlder || taskRunsQuery.isFetching
                      }
                      onClick={taskRunsQuery.older}
                    >
                      {st.history.older}
                    </Button>
                    {taskRunsQuery.page > 0 && (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={taskRunsQuery.latest}
                      >
                        {st.history.latest}
                      </Button>
                    )}
                  </nav>
                  {taskRunsQuery.page > 0 && (
                    <p className="text-muted-foreground text-xs">
                      {st.history.paused}
                    </p>
                  )}
                  {taskRunsQuery.isPending && (
                    <WorkingState label={st.history.loading} className="py-2" />
                  )}
                  {taskRunsQuery.isError && (
                    <ErrorState
                      className="py-2"
                      message={st.history.loadFailed}
                      action={
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={taskRunsQuery.isFetching}
                          onClick={() => void taskRunsQuery.refetch()}
                        >
                          {st.history.retry}
                        </Button>
                      }
                    />
                  )}
                  {!taskRunsQuery.isPending && !taskRunsQuery.isError && (
                    <div
                      className={pageStyles.eyebrow}
                      data-testid="scheduled-task-runs"
                    >
                      {(taskRunsQuery.data ?? []).length === 1
                        ? st.detail.runsCountOne.replace(
                            "{count}",
                            String((taskRunsQuery.data ?? []).length),
                          )
                        : st.detail.runsCount.replace(
                            "{count}",
                            String((taskRunsQuery.data ?? []).length),
                          )}
                    </div>
                  )}
                  {/* Receipts get the least decoration: text on hairlines. */}
                  <div
                    className={cn("flex flex-col divide-y", pageStyles.rows)}
                    data-testid="scheduled-task-run-list"
                  >
                    {(taskRunsQuery.data ?? []).length > 0 ? (
                      (taskRunsQuery.data ?? []).map((run) => (
                        <div key={run.id} className="py-2 text-sm">
                          <div className="font-medium">{runSummary(run)}</div>
                          <div className="text-muted-foreground font-mono text-xs break-all">
                            {run.run_id ?? st.detail.none}
                          </div>
                          <div className="text-muted-foreground text-xs">
                            {formatTimestamp(run.scheduled_for, locale) ??
                              st.detail.none}
                          </div>
                          {run.error && (
                            <div className="text-destructive text-xs [overflow-wrap:anywhere]">
                              {run.error}
                            </div>
                          )}
                        </div>
                      ))
                    ) : !taskRunsQuery.isPending && !taskRunsQuery.isError ? (
                      <div className="text-muted-foreground py-2 text-sm">
                        {st.detail.noRuns}
                      </div>
                    ) : null}
                  </div>
                </div>
              </section>
            ) : null}
          </div>
        </div>
      </WorkspaceBody>

      {/* Delete confirm — follows the agent-card confirm pattern. */}
      <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{st.actions.delete}</DialogTitle>
            <DialogDescription>{st.deleteConfirm}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDeleteOpen(false)}
              disabled={deleteTask.isPending}
            >
              {t.common.cancel}
            </Button>
            <Button
              variant="destructive"
              onClick={() => {
                if (selectedTask) {
                  deleteTask.mutate(selectedTask.id, {
                    onSuccess: () => setDeleteOpen(false),
                  });
                }
              }}
              disabled={deleteTask.isPending}
            >
              {deleteTask.isPending ? t.common.loading : st.actions.delete}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </WorkspaceContainer>
  );
}
