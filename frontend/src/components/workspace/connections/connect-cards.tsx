"use client";

import { CheckCircle2Icon, Loader2Icon, PlugIcon } from "lucide-react";
import { useState } from "react";

import {
  reasonText,
  toolkitLabel,
  useConnect,
  useToolkitStatus,
  type ToolkitStatus,
} from "@/core/integrations/composio";
import { cn } from "@/lib/utils";

/** The Connect button plus its live result line; shared by cards, onboarding and chat. */
export function ConnectButton({
  toolkit,
  handle,
  threadId,
  className,
  onStart,
}: {
  toolkit: string;
  handle?: string;
  threadId?: string;
  className?: string;
  onStart?: () => void;
}) {
  const { phase, start } = useConnect({ toolkit, handle, threadId });
  if (phase.kind === "done") {
    return (
      <span role="status" className="flex items-center gap-1.5 text-sm">
        <CheckCircle2Icon className="size-4 text-emerald-600" aria-hidden />
        {phase.message}
      </span>
    );
  }
  return (
    <span className="flex flex-wrap items-center gap-2">
      <button
        type="button"
        disabled={phase.kind === "working"}
        onClick={() => {
          onStart?.();
          start();
        }}
        className={cn(
          "bg-primary text-primary-foreground inline-flex min-h-11 items-center gap-2 rounded-md px-4 text-sm font-semibold disabled:opacity-60",
          className,
        )}
      >
        {phase.kind === "working" ? (
          <Loader2Icon className="size-4 animate-spin" aria-hidden />
        ) : (
          <PlugIcon className="size-4" aria-hidden />
        )}
        {phase.kind === "working"
          ? "Finish in the sign-in window"
          : `Connect ${toolkitLabel(toolkit)}`}
      </button>
      {phase.kind === "error" && (
        <span role="alert" className="text-destructive text-sm">
          {phase.message}
        </span>
      )}
    </span>
  );
}

function ToolkitRow({ row }: { row: ToolkitStatus }) {
  // Once started here, keep the flow mounted so its result line survives the
  // status refresh that flips this row to connected.
  const [started, setStarted] = useState(false);
  const ready =
    !started && (row.connected || row.reason === "no_account_required");
  return (
    <li className="flex min-h-16 flex-wrap items-center justify-between gap-3 rounded-lg border px-4 py-3">
      <span className="grid gap-0.5">
        <span className="font-medium">{toolkitLabel(row.toolkit)}</span>
        {!ready && !row.connectable && !started && (
          <span className="text-muted-foreground text-sm">
            {reasonText(row.reason)}
          </span>
        )}
      </span>
      {ready ? (
        <span className="flex items-center gap-1.5 text-sm font-medium">
          <CheckCircle2Icon className="size-4 text-emerald-600" aria-hidden />
          {row.connected ? "Connected" : "Ready"}
        </span>
      ) : row.connectable || started ? (
        <ConnectButton toolkit={row.toolkit} onStart={() => setStarted(true)} />
      ) : null}
    </li>
  );
}

/**
 * "Your connections": one row per toolkit this server offers, with the honest
 * reason when it can't be connected yet. Connected first, then connectable.
 */
export function ConnectCards({
  title = "Your connections",
}: {
  title?: string;
}) {
  const { data, isLoading, error } = useToolkitStatus();
  if (isLoading) return null;
  if (error) {
    return (
      <p role="alert" className="text-muted-foreground text-sm">
        {reasonText(error.message) || "Couldn't load your connections."}
      </p>
    );
  }
  if (!data?.length) return null;
  const rank = (row: ToolkitStatus) =>
    row.connected ? 0 : row.connectable ? 1 : 2;
  const rows = [...data].sort((a, b) => rank(a) - rank(b));
  return (
    <section aria-labelledby="connect-cards-title" className="grid gap-3">
      <div className="grid gap-1">
        <h2 id="connect-cards-title" className="text-lg font-semibold">
          {title}
        </h2>
        <p className="text-muted-foreground text-sm">
          Each one signs in with your own account. MomoBot never sees your
          password, and anything it sends or spends still waits for your
          approval.
        </p>
      </div>
      <ul className="grid gap-2">
        {rows.map((row) => (
          <ToolkitRow key={row.toolkit} row={row} />
        ))}
      </ul>
    </section>
  );
}
