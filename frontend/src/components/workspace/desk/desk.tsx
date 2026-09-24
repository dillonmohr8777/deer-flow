"use client";

import { useQueries } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { formatModelLabel } from "@/components/workspace/command-center/model-label";
import {
  EmptyState,
  ErrorState,
  pageStyles,
  StatusTag,
  WorkingState,
  type StatusTone,
} from "@/components/workspace/page-body";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useClients } from "@/core/clients";
import { useConsoleUsage } from "@/core/console";
import { useDeskEnabled } from "@/core/features";
import {
  clientAgentsQueryKey,
  listClientAgents,
  useFleetTemplates,
} from "@/core/fleet";
import { useScheduledTasks } from "@/core/scheduled-tasks/hooks";
import type { ScheduledTask } from "@/core/scheduled-tasks/types";
import { cn } from "@/lib/utils";

import {
  formatWhen,
  groupByDepartment,
  receiptPath,
  recentOutputs,
  summarizeTasks,
  tasksOfBindings,
  tasksOfTemplate,
  type LastRunStatus,
  type TaskSummary,
} from "./desk-data";

import styles from "./desk.module.css";

/**
 * The owner's private home. It renders only when the instance reports
 * features.desk.enabled (config: private_workspace.enabled); anywhere else
 * the route sends people to Command Center before anything Desk-shaped
 * appears.
 */
export function Desk() {
  const { enabled, isLoading } = useDeskEnabled();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && !enabled) router.replace("/workspace/command-center");
  }, [enabled, isLoading, router]);

  useEffect(() => {
    if (enabled) document.title = "Desk | MomoBot";
  }, [enabled]);

  if (!enabled) {
    return <WorkingState label="Loading" className="m-8" />;
  }
  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody className={pageStyles.page}>
        <ScrollArea className="size-full">
          <DeskBody />
        </ScrollArea>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}

function DeskBody() {
  const tasks = useScheduledTasks();
  return (
    <div className={styles.frame} data-testid="desk">
      <header>
        <p className={pageStyles.eyebrow}>
          {new Date().toLocaleDateString(undefined, {
            weekday: "long",
            month: "long",
            day: "numeric",
          })}
        </p>
        <h1 className="mt-1">Desk</h1>
        <p className={cn(pageStyles.lede, "mt-1")}>
          What needs you today, where each client stands, and what every agent
          last did.
        </p>
      </header>
      <Today tasks={tasks} />
      <Clients tasks={tasks.data} tasksError={tasks.isError} />
      <Agents tasks={tasks.data} tasksError={tasks.isError} />
      <ModelLanes />
    </div>
  );
}

function Section({
  id,
  title,
  meta,
  children,
}: {
  id: string;
  title: string;
  meta?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section aria-labelledby={id} className={styles.section}>
      <div className={styles.sectionHead}>
        <h2 id={id}>{title}</h2>
        {meta ? <p className={styles.sectionMeta}>{meta}</p> : null}
      </div>
      {children}
    </section>
  );
}

function ReceiptLink({ task, label }: { task: ScheduledTask; label: string }) {
  const href = receiptPath(task);
  if (!href) return null;
  return (
    <Link
      className={styles.link}
      href={href}
      aria-label={`Open receipt: ${task.title}`}
    >
      {label}
    </Link>
  );
}

function RetryButton({ onRetry }: { onRetry: () => unknown }) {
  return (
    <Button variant="outline" size="sm" onClick={() => void onRetry()}>
      Try again
    </Button>
  );
}

/* ---------- 1. Today ---------- */

function Today({ tasks }: { tasks: ReturnType<typeof useScheduledTasks> }) {
  const outputs = tasks.data ? recentOutputs(tasks.data, Date.now()) : [];
  const everRan = tasks.data?.some((task) => task.last_run_at) ?? false;
  return (
    <Section
      id="desk-today"
      title="Today"
      meta={outputs.length ? `${outputs.length} from the last 24 hours` : null}
    >
      <div className={styles.today}>
        <div className="min-w-0">
          {tasks.isError ? (
            <ErrorState
              message="Couldn't load scheduled work."
              detail={tasks.error.message}
              action={<RetryButton onRetry={tasks.refetch} />}
            />
          ) : tasks.isLoading ? (
            <WorkingState label="Loading scheduled work" />
          ) : outputs.length === 0 ? (
            <EmptyState
              momo="lead"
              title="Nothing is waiting on you"
              action={
                <Link className={styles.link} href="/workspace/scheduled-tasks">
                  Open scheduled tasks
                </Link>
              }
            >
              {everRan
                ? "No scheduled agent finished anything in the last 24 hours. New drafts and results land here."
                : "No scheduled agent has run on this instance yet. Drafts and results land here after the first run."}
            </EmptyState>
          ) : (
            <ul className={cn("divide-y border-b", pageStyles.rows)}>
              {outputs.map((task) => (
                <li key={task.id} className={styles.row}>
                  <span className={styles.name}>
                    <span>{task.title}</span>
                    {task.last_error ? (
                      <span className={styles.sub}>{task.last_error}</span>
                    ) : null}
                  </span>
                  <span className={styles.cell}>
                    <StatusTag tone={task.last_error ? "danger" : "attention"}>
                      {task.last_error ? "Failed" : "Ready for review"}
                    </StatusTag>
                  </span>
                  <span className={cn(styles.cell, pageStyles.figure)}>
                    {formatWhen(task.last_run_at!)}
                  </span>
                  <ReceiptLink task={task} label="Open receipt" />
                </li>
              ))}
            </ul>
          )}
        </div>
        <aside
          aria-labelledby="desk-approvals"
          className={cn(pageStyles.sheet, styles.notice)}
        >
          <div className="flex items-center justify-between gap-3">
            <h3 id="desk-approvals">Approvals</h3>
            <StatusTag tone="unknown">Not wired</StatusTag>
          </div>
          <p className={styles.muted}>
            This workspace has no approval queue yet, so nothing can be approved
            or sent from here. Agents save drafts instead of sending; review
            each one from its receipt.
          </p>
        </aside>
      </div>
    </Section>
  );
}

/* ---------- 2. Clients ---------- */

const CLIENT_STATUS: Record<string, string> = {
  active: "Active",
  prospect: "Prospect",
  inactive: "Inactive",
};

function Clients({
  tasks,
  tasksError,
}: {
  tasks: ScheduledTask[] | undefined;
  tasksError: boolean;
}) {
  const clients = useClients();
  const bindings = useQueries({
    queries: (clients.data ?? []).map((client) => ({
      queryKey: clientAgentsQueryKey(client.id),
      queryFn: () => listClientAgents(client.id),
    })),
  });
  const list = clients.data ?? [];
  return (
    <Section
      id="desk-clients"
      title="Clients"
      meta={
        list.length
          ? `${list.length} ${list.length === 1 ? "client" : "clients"}`
          : null
      }
    >
      {clients.isError ? (
        <ErrorState
          message="Couldn't load the client roster."
          detail={clients.error.message}
          action={<RetryButton onRetry={clients.refetch} />}
        />
      ) : clients.isLoading ? (
        <WorkingState label="Loading clients" />
      ) : list.length === 0 ? (
        <EmptyState momo="analytics" title="No clients yet">
          Clients in the roster show up here with their next deliverable and
          last report.
        </EmptyState>
      ) : (
        <ul className={cn("divide-y border-b", pageStyles.rows)}>
          {list.map((client, index) => {
            const query = bindings[index];
            const summary =
              query?.data && tasks
                ? summarizeTasks(tasksOfBindings(query.data, tasks))
                : null;
            const failed = (query?.isError ?? false) || tasksError;
            return (
              <li key={client.id} className={styles.row}>
                <span className={styles.name}>
                  <span>{client.display_name}</span>
                  <span className={styles.sub}>
                    {CLIENT_STATUS[client.status] ?? client.status}
                  </span>
                </span>
                <span className={cn(styles.cell, styles.wide)}>
                  {summary ? (
                    <NextDue summary={summary} />
                  ) : (
                    <span className={styles.muted}>
                      {failed ? "Schedule unavailable" : "Loading"}
                    </span>
                  )}
                </span>
                <span className={cn(styles.cell, styles.wide)}>
                  {summary ? <LastReport summary={summary} /> : null}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </Section>
  );
}

function NextDue({ summary }: { summary: TaskSummary }) {
  if (summary.next?.next_run_at) {
    return (
      <>
        <span className={styles.muted}>Next due </span>
        {summary.next.title}, {formatWhen(summary.next.next_run_at)}
      </>
    );
  }
  return (
    <span className={styles.muted}>
      {summary.paused ? "Schedules paused" : "No agents scheduled"}
    </span>
  );
}

function LastReport({ summary }: { summary: TaskSummary }) {
  const last = summary.last;
  if (!last?.last_run_at) {
    return <span className={styles.muted}>No report yet</span>;
  }
  return (
    <>
      <span className={styles.muted}>Last report </span>
      <ReceiptLink
        task={last}
        label={`${formatWhen(last.last_run_at)}${summary.lastStatus === "failed" ? ", failed" : ""}`}
      />
    </>
  );
}

/* ---------- 3. Agents by department ---------- */

const LAST_RUN: Record<LastRunStatus, [StatusTone, string]> = {
  running: ["active", "Running"],
  failed: ["danger", "Failed"],
  completed: ["ok", "Completed"],
  none: ["idle", "No runs yet"],
};

function Agents({
  tasks,
  tasksError,
}: {
  tasks: ScheduledTask[] | undefined;
  tasksError: boolean;
}) {
  const templates = useFleetTemplates();
  const groups = groupByDepartment(templates.data ?? []);
  const scheduled =
    tasks && templates.data
      ? templates.data.filter((t) => tasksOfTemplate(t.id, tasks).length > 0)
          .length
      : null;
  return (
    <Section
      id="desk-agents"
      title="Agents"
      meta={
        scheduled !== null && templates.data?.length
          ? `${scheduled} of ${templates.data.length} scheduled`
          : null
      }
    >
      {templates.isError ? (
        <ErrorState
          message="Couldn't load the agent roster."
          detail={templates.error.message}
          action={<RetryButton onRetry={templates.refetch} />}
        />
      ) : templates.isLoading ? (
        <WorkingState label="Loading agents" />
      ) : groups.length === 0 ? (
        <EmptyState momo="builder" title="No agents on this instance yet">
          Fleet templates mounted on this instance show up here, grouped by
          department.
        </EmptyState>
      ) : (
        <div className="flex flex-col">
          {groups.map((group) => (
            <div
              key={group.department}
              className={cn(styles.group, "border-b")}
              role="group"
              aria-label={group.department}
            >
              <p className={cn(pageStyles.eyebrow, "pt-3 lg:pt-0")}>
                {group.department}
              </p>
              <ul className={cn("divide-y", pageStyles.rows)}>
                {group.templates.map((template) => {
                  const summary = tasks
                    ? summarizeTasks(tasksOfTemplate(template.id, tasks))
                    : null;
                  return (
                    <li key={template.id} className={styles.row}>
                      <span className={styles.name}>
                        <span>{template.name}</span>
                        <span className={styles.sub}>
                          {formatModelLabel(template.model) || "Model not set"}
                        </span>
                      </span>
                      <span className={styles.cell}>
                        {summary ? (
                          <NextRun summary={summary} />
                        ) : (
                          <span className={styles.muted}>
                            {tasksError ? "Unavailable" : "Loading"}
                          </span>
                        )}
                      </span>
                      <span className={styles.cell}>
                        {summary ? (
                          <StatusTag tone={LAST_RUN[summary.lastStatus][0]}>
                            {LAST_RUN[summary.lastStatus][1]}
                            {summary.last?.last_run_at
                              ? `, ${formatWhen(summary.last.last_run_at)}`
                              : ""}
                          </StatusTag>
                        ) : null}
                      </span>
                      {summary?.last ? (
                        <ReceiptLink task={summary.last} label="Receipt" />
                      ) : null}
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </div>
      )}
    </Section>
  );
}

function NextRun({ summary }: { summary: TaskSummary }) {
  if (summary.next?.next_run_at) {
    return (
      <>
        <span className={styles.muted}>Next </span>
        {formatWhen(summary.next.next_run_at)}
      </>
    );
  }
  return (
    <span className={styles.muted}>
      {summary.paused ? "Paused" : "Not scheduled"}
    </span>
  );
}

/* ---------- 4. Model lanes ---------- */

function ModelLanes() {
  const usage = useConsoleUsage();
  const data = usage.data;
  const tokens = new Intl.NumberFormat(undefined, { notation: "compact" });
  const money = (value: number | null) =>
    value !== null && data?.currency
      ? new Intl.NumberFormat(undefined, {
          style: "currency",
          currency: data.currency,
        }).format(value)
      : "Not priced";
  const rows = Object.entries(data?.by_model ?? {}).sort(
    ([, a], [, b]) => b.tokens - a.tokens,
  );
  return (
    <Section
      id="desk-lanes"
      title="Model lanes"
      meta={
        rows.some(([, row]) => row.cost === null) && data?.total_cost !== null
          ? "Last 14 days. Spend counts priced models only."
          : "Last 14 days"
      }
    >
      {usage.isError ? (
        <ErrorState
          message="Couldn't load model usage."
          detail={usage.error.message}
          action={<RetryButton onRetry={usage.refetch} />}
        />
      ) : usage.isLoading || !data ? (
        <WorkingState label="Loading model usage" />
      ) : rows.length === 0 ? (
        <EmptyState momo="analytics" title="No model calls yet">
          Runs, tokens and spend for each model lane show up here after the
          first agent run.
        </EmptyState>
      ) : (
        <table className={styles.table}>
          <thead>
            <tr>
              <th scope="col">Model</th>
              <th scope="col">Runs</th>
              <th scope="col">Tokens</th>
              <th scope="col">Spend</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([model, row]) => (
              <tr key={model}>
                <th scope="row" className="font-normal">
                  {formatModelLabel(model) || model}
                </th>
                <td>{row.runs}</td>
                <td>{tokens.format(row.tokens)}</td>
                <td>{money(row.cost)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <td>Total</td>
              <td>{data.total_runs}</td>
              <td>{tokens.format(data.total_tokens)}</td>
              <td>{money(data.total_cost)}</td>
            </tr>
          </tfoot>
        </table>
      )}
    </Section>
  );
}
