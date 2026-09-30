"use client";

import { Button } from "@/components/ui/button";
import { pageStyles } from "@/components/workspace/page-body";
import {
  FRAMEWORK_LABELS,
  isWorkflowActive,
  type WorkflowRun,
} from "@/core/workflows/types";
import { cn } from "@/lib/utils";

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
  const incomplete =
    run.usage.complete === false || (run.usage.unknown_model_calls ?? 0) > 0;
  return (
    <section
      aria-label="Workflow run"
      className={cn(pageStyles.sheet, "min-w-0 space-y-5 border p-4")}
    >
      <div className="space-y-2">
        {/* A record's title, under the page's "Your runs" h2: Nunito, not a
            second Fraunces heading louder than its section. */}
        <h3 className="text-lg font-bold break-words">{run.title}</h3>
        <p role="status" className="text-sm">
          {run.status} · {FRAMEWORK_LABELS[run.framework] ?? run.framework}
          {run.status === "completed"
            ? run.accepted
              ? " · acceptance passed"
              : " · output not accepted"
            : ""}
        </p>
        <p className="text-muted-foreground text-xs break-all">Run {run.id}</p>
      </div>
      {run.status === "interrupted" && (
        <p className="text-sm">
          This run was interrupted. Resume keeps its original checkpoints and
          remaining budget.
        </p>
      )}
      {run.error && (
        <p role="alert" className="text-destructive text-sm break-words">
          {run.error}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
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
      <ol className="space-y-3" aria-label="Recorded workflow steps">
        {run.steps.map((step, index) => (
          <li
            key={`${step.name}-${index}`}
            className="space-y-1 border-t pt-3 text-sm"
          >
            <p className="break-words">
              {step.name} · {step.status}
            </p>
            {step.worker_id && (
              <p className="text-muted-foreground text-xs break-all">
                Worker {step.worker_id}
              </p>
            )}
            {(step.model ?? step.effort) && (
              <p className="text-muted-foreground text-xs">
                {step.model ? `Model ${step.model}` : "Model not recorded"}
                {step.effort ? ` · effort ${step.effort}` : ""}
              </p>
            )}
            {step.detail && (
              <p className="leading-relaxed break-words">{step.detail}</p>
            )}
          </li>
        ))}
      </ol>
      <p className="text-muted-foreground text-sm">
        {run.usage.model_calls} model attempts ·{" "}
        {incomplete ? "Known minimum: " : ""}
        {run.usage.input_tokens} input tokens · {run.usage.output_tokens} output
        tokens ·{" "}
        {run.usage.cost === null
          ? "Cost unavailable"
          : `Recorded cost ${run.usage.cost}`}
      </p>
      {incomplete && (
        <p className="text-muted-foreground text-sm">
          Usage is incomplete. {run.usage.unknown_model_calls ?? "Unrecorded"}{" "}
          attempts have unresolved usage; these token counts are not final
          totals.
        </p>
      )}
      {run.output && (
        <div className="space-y-2">
          <h3 className="text-base">Recorded output</h3>
          <pre className="bg-muted max-h-96 overflow-auto rounded-md p-3 text-xs leading-relaxed break-words whitespace-pre-wrap">
            {JSON.stringify(run.output, null, 2)}
          </pre>
        </div>
      )}
      {run.evidence.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-base">Recorded evidence</h3>
          <ul className="space-y-2">
            {run.evidence.map((evidence, index) => (
              <li key={index} className="text-sm break-all">
                <p>
                  {evidence.kind}: {evidence.reference}
                </p>
                {evidence.sha256 && (
                  <p className="text-muted-foreground text-xs">
                    SHA-256 {evidence.sha256}
                  </p>
                )}
                {evidence.bytes !== undefined && (
                  <p className="text-muted-foreground text-xs">
                    {evidence.bytes} bytes
                  </p>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
