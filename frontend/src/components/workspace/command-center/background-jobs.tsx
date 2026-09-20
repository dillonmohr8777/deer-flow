"use client";

import { ArrowUpRight, Layers3, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { useAgents } from "@/core/agents";
import {
  useConsoleRuns,
  useConsoleStats,
  type ConsoleRunItem,
} from "@/core/console";
import { pathOfThread } from "@/core/threads/utils";

const STATUS_LABEL: Record<string, string> = {
  pending: "Queued",
  running: "Running",
  success: "Completed",
  error: "Failed",
  timeout: "Timed out",
};

function statusLabel(status: string) {
  return STATUS_LABEL[status] ?? "Status unknown";
}

function isTerminal(status: string) {
  return status !== "pending" && status !== "running";
}

export function BackgroundJobs() {
  const [open, setOpen] = useState(false);
  const stats = useConsoleStats();
  // Never turn a loading/error response into a reassuring zero-work count.
  if (!stats.data || stats.isError) return null;
  return (
    <div className="fixed right-4 bottom-4 z-40 w-72 max-w-[calc(100vw-2rem)] rounded-xl border border-[#8e8578] bg-[#fbf8f4] text-[#14181b]">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        aria-controls="momentum-background-jobs"
        aria-label={`Background work, ${stats.data.active_runs} queued or running jobs`}
        className="flex w-full items-center gap-3 rounded-xl px-4 py-3 text-left text-sm font-semibold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#a35309]"
      >
        <Layers3 size={17} className="text-[#155e86]" />
        <span className="flex-1">Background work</span>
        <span className="tabular-nums" aria-hidden="true">
          {stats.data.active_runs}
        </span>
        {open && <X size={15} />}
      </button>
      {open && (
        <div
          id="momentum-background-jobs"
          className="max-h-80 overflow-y-auto border-t border-[#dcd6cc] px-4 pb-4"
        >
          {stats.data.active_runs === 0 ? (
            <p className="py-4 text-sm text-[#636465]">
              No pending or running jobs.
            </p>
          ) : (
            <>
              <h3 className="pt-3 text-xs font-bold tracking-wide text-[#636465] uppercase">
                Active work
              </h3>
              <ActiveJobs status="running" />
              <ActiveJobs status="pending" />
            </>
          )}
          <h3 className="pt-3 text-xs font-bold tracking-wide text-[#636465] uppercase">
            Latest receipts
          </h3>
          <RecentReceipts />
          <Link
            className="mt-3 flex items-center gap-2 text-sm font-semibold text-[#155e86] underline underline-offset-4"
            href="/workspace/command-center"
          >
            Open Command Center <ArrowUpRight size={14} />
          </Link>
        </div>
      )}
    </div>
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
      <p className="py-3 text-sm text-[#636465]">
        No {statusLabel(status).toLowerCase()} jobs right now.
      </p>
    );
  return (
    <>
      {query.data.runs.map((run) => (
        <RunRow key={run.run_id} run={run} agents={agents} />
      ))}
      {query.data?.has_more && (
        <p className="pt-2 text-xs text-[#636465]">
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
      <p className="py-3 text-sm text-[#636465]">
        No completed, failed, or timed-out runs in the latest 20.
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
      key={run.run_id}
      href={pathOfThread(
        run.thread_id,
        agentName ? { agent_name: agentName } : undefined,
      )}
      aria-label={`${title}, ${label}`}
      className="block border-b border-[#dcd6cc] py-3 text-sm hover:underline focus-visible:outline-2 focus-visible:outline-[#a35309]"
    >
      <span className="block truncate font-semibold">{title}</span>
      <span className="text-xs text-[#636465]">
        {label} · {run.model_name ?? "Model not recorded"} ·{" "}
        {run.total_tokens.toLocaleString()} tokens
      </span>
      {run.error && (
        <span className="block truncate text-xs text-[#636465]">
          Error: {run.error}
        </span>
      )}
    </Link>
  );
}
