"use client";

import * as PopoverPrimitive from "@radix-ui/react-popover";
import { Activity, ArrowUpRight } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar";
import { useAgents } from "@/core/agents";
import {
  useConsoleRuns,
  useConsoleStats,
  type ConsoleRunItem,
} from "@/core/console";
import { isStaticWebsiteOnly } from "@/core/static-mode";
import { pathOfThread } from "@/core/threads/utils";
import { cn } from "@/lib/utils";

import { formatModelLabel } from "./model-label";

const STATUS_LABEL: Record<string, string> = {
  pending: "Queued",
  running: "Running",
  success: "Completed",
  error: "Failed",
  timeout: "Timed out",
  interrupted: "Interrupted",
};

function statusLabel(status: string) {
  return STATUS_LABEL[status] ?? "Status unknown";
}

function isTerminal(status: string) {
  return status !== "pending" && status !== "running";
}

/**
 * Background work, docked where it never covers content: a row in the sidebar
 * footer (desktop, and the sidebar sheet on phones) or a compact icon in a
 * page header. The count is live; a count that failed to load says
 * "Unavailable" instead of a reassuring zero.
 */
export function BackgroundJobs({
  variant = "sidebar",
}: {
  variant?: "sidebar" | "header";
}) {
  const stats = useConsoleStats();
  if (isStaticWebsiteOnly()) return null;
  // undefined: still loading. null: failed, so unknown rather than 0.
  const count = stats.isError ? null : stats.data?.active_runs;
  const name =
    count === undefined
      ? "Background work, loading"
      : count === null
        ? "Background work, count unavailable"
        : `Background work, ${count} queued or running jobs`;

  if (variant === "header")
    return (
      <PopoverPrimitive.Root>
        <PopoverPrimitive.Trigger asChild>
          <Button variant="ghost" size="sm" aria-label={name}>
            <Activity />
            <Count count={count} />
          </Button>
        </PopoverPrimitive.Trigger>
        <Panel count={count} side="bottom" />
      </PopoverPrimitive.Root>
    );
  return <SidebarRow count={count} name={name} />;
}

function SidebarRow({
  count,
  name,
}: {
  count: number | null | undefined;
  name: string;
}) {
  const { isMobile } = useSidebar();
  return (
    <PopoverPrimitive.Root>
      <SidebarMenu>
        <SidebarMenuItem>
          <SidebarMenuButton asChild tooltip={name}>
            <PopoverPrimitive.Trigger aria-label={name}>
              <Activity />
              <span>Background work</span>
              <Count count={count} />
            </PopoverPrimitive.Trigger>
          </SidebarMenuButton>
          {/* Collapsed sidebar: the label and count are clipped, so live work
              shows as a dot on the icon (the tooltip and name carry the number). */}
          {count ? (
            <span
              aria-hidden="true"
              className="bg-primary absolute top-1 right-1 hidden size-2 rounded-full group-data-[collapsible=icon]:block"
            />
          ) : null}
        </SidebarMenuItem>
      </SidebarMenu>
      <Panel count={count} side={isMobile ? "top" : "right"} />
    </PopoverPrimitive.Root>
  );
}

/** Visible count. Colour only when there is live work: state, not decoration. */
function Count({ count }: { count: number | null | undefined }) {
  if (count === undefined) return null;
  if (count === null)
    return (
      <span aria-hidden="true" className="text-muted-foreground ml-auto text-xs">
        Unavailable
      </span>
    );
  return (
    <span
      aria-hidden="true"
      className={cn(
        "ml-auto min-w-5 rounded-full px-1.5 text-center text-xs font-bold tabular-nums",
        count > 0 ? "bg-primary text-primary-foreground" : "text-muted-foreground",
      )}
    >
      {count}
    </span>
  );
}

function Panel({
  count,
  side,
}: {
  count: number | null | undefined;
  side: "top" | "right" | "bottom";
}) {
  return (
    <PopoverPrimitive.Portal>
      <PopoverPrimitive.Content
        side={side}
        align="end"
        sideOffset={8}
        collisionPadding={16}
        aria-label="Background work"
        className="bg-popover text-popover-foreground z-50 max-h-(--radix-popover-content-available-height) w-80 max-w-[calc(100vw-2rem)] overflow-y-auto rounded-lg border px-4 pb-4 shadow-md"
      >
        {count === 0 ? (
          <p className="text-muted-foreground py-4 text-sm">
            No pending or running jobs.
          </p>
        ) : (
          <>
            <h3 className="text-muted-foreground pt-3 text-xs font-bold tracking-wide uppercase">
              Active work
            </h3>
            <ActiveJobs status="running" />
            <ActiveJobs status="pending" />
          </>
        )}
        <h3 className="text-muted-foreground pt-3 text-xs font-bold tracking-wide uppercase">
          Latest receipts
        </h3>
        <RecentReceipts />
        <Link
          className="text-primary mt-3 flex items-center gap-2 text-sm font-bold underline underline-offset-4"
          href="/workspace/command-center"
        >
          Open Command Center <ArrowUpRight size={14} />
        </Link>
      </PopoverPrimitive.Content>
    </PopoverPrimitive.Portal>
  );
}

function ActiveJobs({ status }: { status: "running" | "pending" }) {
  const query = useConsoleRuns({ status });
  const { agents } = useAgents();
  if (query.isLoading)
    return (
      <p role="status" className="py-3 text-sm">
        Loading {statusLabel(status).toLowerCase()} jobs…
      </p>
    );
  if (query.isError)
    return (
      <p role="alert" className="py-3 text-sm">
        Could not load {statusLabel(status).toLowerCase()} jobs. Earlier
        receipts below may be stale.
      </p>
    );
  if (!query.data || query.data.runs.length === 0)
    return (
      <p className="text-muted-foreground py-3 text-sm">
        No {statusLabel(status).toLowerCase()} jobs right now.
      </p>
    );
  return (
    <>
      {query.data.runs.map((run) => (
        <RunRow key={run.run_id} run={run} agents={agents} />
      ))}
      {query.data?.has_more && (
        <p className="text-muted-foreground pt-2 text-xs">
          Showing the latest 20 {statusLabel(status).toLowerCase()} jobs.
        </p>
      )}
    </>
  );
}

function RecentReceipts() {
  const query = useConsoleRuns({});
  const { agents } = useAgents();
  if (query.isLoading)
    return (
      <p role="status" className="py-3 text-sm">
        Loading latest receipts…
      </p>
    );
  if (query.isError)
    return (
      <p role="alert" className="py-3 text-sm">
        Could not load latest receipts.
      </p>
    );
  const receipts = (query.data?.runs ?? []).filter((run) =>
    isTerminal(run.status),
  );
  if (receipts.length === 0)
    return (
      <p className="text-muted-foreground py-3 text-sm">
        No completed, failed, timed-out, or interrupted runs in the latest 20.
      </p>
    );
  return (
    <>
      {receipts.slice(0, 5).map((run) => (
        <RunRow key={run.run_id} run={run} agents={agents} />
      ))}
    </>
  );
}

/** A receipt: plain text on purpose, the least decorated thing on screen. */
function RunRow({
  run,
  agents,
}: {
  run: ConsoleRunItem;
  agents: { name: string }[];
}) {
  const agentName = agents.find(
    (agent) => agent.name === run.assistant_id,
  )?.name;
  const title = run.thread_title ?? "Untitled assignment";
  const label = statusLabel(run.status);
  return (
    <Link
      href={pathOfThread(
        run.thread_id,
        agentName ? { agent_name: agentName } : undefined,
      )}
      aria-label={`${title}, ${label}`}
      className="hover:bg-accent block border-b py-2.5 text-sm"
    >
      <span className="block truncate font-bold">{title}</span>
      <span className="text-muted-foreground text-xs">
        {label} ·{" "}
        {run.model_name ? formatModelLabel(run.model_name) : "Model not recorded"}{" "}
        · <span className="tabular-nums">{run.total_tokens.toLocaleString()}</span>{" "}
        tokens
      </span>
      {run.error && (
        <span className="text-destructive block truncate text-xs">
          Error: {run.error}
        </span>
      )}
    </Link>
  );
}
