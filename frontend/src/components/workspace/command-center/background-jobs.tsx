"use client";

import { ArrowUpRight, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

import { useAgents } from "@/core/agents";
import {
  useConsoleRuns,
  useConsoleStats,
  type ConsoleRunItem,
} from "@/core/console";
import { pathOfThread } from "@/core/threads/utils";

import { MomentumGlyph } from "./momentum-glyph";

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

export function BackgroundJobs() {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();
  const stats = useConsoleStats();
  // Never turn a loading/error response into a reassuring zero-work count.
  if (!stats.data || stats.isError) return null;
  return (
    <div
      className={`fixed right-4 z-40 max-w-[calc(100vw-2rem)] overflow-hidden rounded-2xl border border-[#91b7d6] bg-white text-[#07172f] shadow-[0_16px_44px_rgba(24,84,134,0.18)] ${pathname.includes("/chats/") ? "bottom-32 sm:bottom-4" : "bottom-4"} sm:w-72 ${open ? "w-72" : "w-auto"}`}
    >
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        aria-controls="momentum-background-jobs"
        aria-label={`Background work, ${stats.data.active_runs} queued or running jobs`}
        className="flex w-full items-center gap-3 rounded-2xl bg-[linear-gradient(105deg,#f8fcff,#edf7ff)] px-4 py-3 text-left text-sm font-bold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#f39b35]"
      >
        <MomentumGlyph seed="system:background-work" size={24} />
        <span className={open ? "flex-1" : "hidden sm:block sm:flex-1"}>
          Background work
        </span>
        <span className="tabular-nums" aria-hidden="true">
          {stats.data.active_runs}
        </span>
        {open && <X size={15} />}
      </button>
      {open && (
        <div
          id="momentum-background-jobs"
          className="max-h-[50dvh] overflow-y-auto border-t border-[#d2e3f2] px-4 pb-4 sm:max-h-80"
        >
          {stats.data.active_runs === 0 ? (
            <p className="py-4 text-sm text-[#50657b]">
              No pending or running jobs.
            </p>
          ) : (
            <>
              <h3 className="pt-3 text-xs font-bold tracking-wide text-[#50657b] uppercase">
                Active work
              </h3>
              <ActiveJobs status="running" />
              <ActiveJobs status="pending" />
            </>
          )}
          <h3 className="pt-3 text-xs font-bold tracking-wide text-[#50657b] uppercase">
            Latest receipts
          </h3>
          <RecentReceipts />
          <Link
            className="mt-3 flex items-center gap-2 text-sm font-bold text-[#075bd8] underline underline-offset-4"
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
      <p className="py-3 text-sm text-[#50657b]">
        No {statusLabel(status).toLowerCase()} jobs right now.
      </p>
    );
  return (
    <>
      {query.data.runs.map((run) => (
        <RunRow key={run.run_id} run={run} agents={agents} />
      ))}
      {query.data?.has_more && (
        <p className="pt-2 text-xs text-[#50657b]">
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
      <p className="py-3 text-sm text-[#50657b]">
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
      className="flex gap-2 border-b border-[#d2e3f2] py-3 text-sm hover:bg-[#edf7ff] focus-visible:outline-2 focus-visible:outline-[#f39b35]"
    >
      <MomentumGlyph seed={`thread:${run.thread_id}`} size={28} />
      <span className="min-w-0 flex-1">
        <span className="block truncate font-bold text-[#092a57]">{title}</span>
        <span className="text-xs text-[#50657b]">
          {label} ·{" "}
          <span className="font-bold text-[#00668e]">
            {run.model_name ?? "Model not recorded"}
          </span>{" "}
          ·{" "}
          <span className="font-bold text-[#5b3bd8]">
            {run.total_tokens.toLocaleString()} tokens
          </span>
        </span>
        {run.error && (
          <span className="block truncate text-xs text-[#b4233e]">
            Error: {run.error}
          </span>
        )}
      </span>
    </Link>
  );
}
