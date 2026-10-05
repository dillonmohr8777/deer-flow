"use client";

import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { pageStyles, StatusTag } from "@/components/workspace/page-body";
import { toDateTimeAttr } from "@/core/utils/datetime";
import {
  FRAMEWORK_LABELS,
  isWorkflowActive,
  type WorkflowRun,
} from "@/core/workflows/types";
import { cn } from "@/lib/utils";

import {
  byteSize,
  evidenceKind,
  explanation,
  humanize,
  runState,
  runTime,
  stepDetail,
  stepName,
  stepsOnce,
  stepState,
} from "./workflow-words";

/** Provider cost in US dollars; a sub-cent run is not "$0". */
function usd(cost: number): string {
  if (cost > 0 && cost < 0.01) return "Under $0.01";
  return cost.toLocaleString("en-US", { style: "currency", currency: "USD" });
}

/** "2 attempts have", "1 attempt has", or "Some attempts have" when unknown. */
function unresolvedAttempts(count: number | undefined): string {
  if (!count) return "Some attempts have";
  return count === 1 ? "1 attempt has" : `${count} attempts have`;
}

/** A section name inside the receipt, in the label voice. */
function Label({ children }: { children: ReactNode }) {
  return <h4 className={cn(pageStyles.eyebrow, "mb-2")}>{children}</h4>;
}

/** One output field: text reads as text, a list as a list, anything else as JSON. */
function OutputValue({ value }: { value: unknown }) {
  if (typeof value === "string" || typeof value === "number")
    return <p className="whitespace-pre-wrap">{String(value)}</p>;
  if (typeof value === "boolean") return <p>{value ? "Yes" : "No"}</p>;
  if (Array.isArray(value) && value.every((item) => typeof item === "string"))
    return (
      <ul className="ml-5 list-disc space-y-1">
        {value.map((item, index) => (
          <li key={index}>{item}</li>
        ))}
      </ul>
    );
  return (
    <pre className="bg-muted max-h-96 overflow-auto rounded-sm p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

export function WorkflowRunDetail({
  run,
  busy,
  mayCancel,
  mayResume,
  onAction,
  onDownload,
}: {
  run: WorkflowRun;
  busy: boolean;
  mayCancel: boolean;
  mayResume: boolean;
  onAction: (action: "cancel" | "resume") => void;
  onDownload: () => void;
}) {
  const state = runState(run);
  const steps = stepsOnce(run.steps);
  const incomplete =
    run.usage.complete === false || (run.usage.unknown_model_calls ?? 0) > 0;
  const atLeast = incomplete ? ", at least" : "";
  const facts: [string, string][] = [
    ["Model attempts", run.usage.model_calls.toLocaleString()],
    [`Input tokens${atLeast}`, run.usage.input_tokens.toLocaleString()],
    [`Output tokens${atLeast}`, run.usage.output_tokens.toLocaleString()],
    ["Cost", run.usage.cost === null ? "Unavailable" : usd(run.usage.cost)],
  ];
  return (
    <section
      aria-label="Workflow run"
      className={cn(pageStyles.sheet, "min-w-0 space-y-5 border p-4 sm:p-5")}
    >
      <div className="space-y-1.5">
        {/* A record's title, under the page's "Your runs" h2: Nunito, not a
            second Fraunces heading louder than its section. */}
        <h3 className="text-lg leading-snug font-bold break-words">
          {run.title}
        </h3>
        <p role="status" className="text-sm">
          <StatusTag tone={state.tone}>{state.label}</StatusTag>
          <span className="text-muted-foreground">
            {" · "}
            {FRAMEWORK_LABELS[run.framework] ?? run.framework}
          </span>
        </p>
        <p className="text-muted-foreground text-sm">
          Started{" "}
          <time
            dateTime={toDateTimeAttr(run.created_at)}
            title={new Date(run.created_at).toLocaleString()}
          >
            {runTime(run.created_at)}
          </time>
        </p>
      </div>
      {run.status === "interrupted" && (
        <p className="text-sm">
          This run was interrupted. Resume keeps its original checkpoints and
          remaining budget.
        </p>
      )}
      {run.error && (
        <p role="alert" className="text-destructive text-sm break-words">
          {explanation(new Error(run.error))}
        </p>
      )}
      <div className="flex flex-wrap gap-2 empty:hidden">
        {(isWorkflowActive(run.status) || run.status === "interrupted") &&
          mayCancel && (
            <Button
              variant="outline"
              className="min-h-11"
              disabled={busy}
              onClick={() => onAction("cancel")}
            >
              Cancel run
            </Button>
          )}
        {run.status === "interrupted" && (
          <Button
            className="min-h-11"
            disabled={busy || !mayResume}
            onClick={() => onAction("resume")}
          >
            Resume interrupted run
          </Button>
        )}
        {run.status === "completed" && run.accepted && run.artifact && (
          <Button
            variant="outline"
            className="min-h-11"
            disabled={busy}
            onClick={onDownload}
          >
            Download accepted artifact
          </Button>
        )}
      </div>
      <div className="border-t pt-4">
        <Label>Steps</Label>
        {steps.length === 0 ? (
          <p className="text-muted-foreground text-sm">
            No steps recorded yet.
          </p>
        ) : (
          <ol
            className={cn(pageStyles.rows, "max-w-[62ch] divide-y")}
            aria-label="Recorded workflow steps"
          >
            {steps.map((step) => {
              const tag = stepState(step, run);
              const detail = stepDetail(step.detail);
              return (
                <li
                  key={step.name}
                  className="flex items-start justify-between gap-3 py-2.5 text-sm"
                >
                  <div className="min-w-0 space-y-0.5">
                    <p className="font-semibold break-words">
                      {stepName(step.name)}
                    </p>
                    {detail && (
                      <p className="leading-relaxed break-words">{detail}</p>
                    )}
                    {step.model && (
                      <p className="text-muted-foreground text-xs">
                        <span className="font-mono break-all">
                          {step.model}
                        </span>
                        {step.effort ? `, ${step.effort} effort` : ""}
                      </p>
                    )}
                  </div>
                  <StatusTag tone={tag.tone} className="mt-0.5 shrink-0">
                    {tag.label}
                  </StatusTag>
                </li>
              );
            })}
          </ol>
        )}
      </div>
      {run.output && (
        <div className="border-t pt-4">
          <Label>{run.accepted ? "Result" : "Result, not accepted"}</Label>
          <dl className="max-w-[62ch] space-y-3 text-sm leading-relaxed break-words">
            {Object.entries(run.output).map(([key, value]) => (
              <div key={key} className="space-y-1">
                <dt className="font-semibold">{humanize(key)}</dt>
                <dd>
                  <OutputValue value={value} />
                </dd>
              </div>
            ))}
          </dl>
        </div>
      )}
      {run.evidence.length > 0 && (
        <div className="border-t pt-4">
          <Label>Evidence</Label>
          <ul className="space-y-3 text-sm">
            {run.evidence.map((evidence, index) => (
              <li key={index} className="min-w-0 space-y-0.5">
                <p className="font-semibold">{evidenceKind(evidence.kind)}</p>
                <p className="font-mono text-xs break-all">
                  {evidence.reference}
                </p>
                {(evidence.bytes !== undefined || evidence.sha256) && (
                  <p className="text-muted-foreground text-xs break-all">
                    {evidence.bytes !== undefined && byteSize(evidence.bytes)}
                    {evidence.bytes !== undefined && evidence.sha256 && " · "}
                    {evidence.sha256 && (
                      <>
                        SHA-256{" "}
                        <span className="font-mono">{evidence.sha256}</span>
                      </>
                    )}
                  </p>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className="border-t pt-4">
        <Label>Record</Label>
        <dl className="grid max-w-[62ch] grid-cols-2 gap-x-4 gap-y-3 text-sm sm:grid-cols-4">
          {facts.map(([name, value]) => (
            <div key={name} className="min-w-0">
              <dt className="text-muted-foreground text-xs">{name}</dt>
              <dd className="font-semibold tabular-nums">{value}</dd>
            </div>
          ))}
          <div className="col-span-full min-w-0">
            <dt className="text-muted-foreground text-xs">Run id</dt>
            <dd className="font-mono text-xs break-all">{run.id}</dd>
          </div>
        </dl>
        {incomplete && (
          <p className="text-muted-foreground mt-3 text-sm">
            Known minimum. {unresolvedAttempts(run.usage.unknown_model_calls)}{" "}
            unresolved usage, so these token counts are not final totals.
          </p>
        )}
      </div>
    </section>
  );
}
