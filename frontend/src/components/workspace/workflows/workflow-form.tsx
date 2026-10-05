"use client";

import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { pageStyles } from "@/components/workspace/page-body";
import {
  exampleDraft,
  fieldLabel,
  parseWorkflowInputs,
  resolvedSchema,
  schemaType,
  type InputDraft,
} from "@/core/workflows/inputs";
import {
  FRAMEWORKS,
  FRAMEWORK_LABELS,
  type WorkflowDefinition,
  type WorkflowFramework,
  type WorkflowInput,
  type WorkflowStatus,
} from "@/core/workflows/types";
import { cn } from "@/lib/utils";

import { categoryName, fieldHint, humanize, stepName } from "./workflow-words";

const CONTROL =
  "border-input bg-background focus-visible:ring-ring min-h-11 w-full min-w-0 rounded-md border px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 disabled:opacity-60";

export function WorkflowForm({
  definition,
  status,
  locked,
  mayCreate,
  onRun,
}: {
  definition: WorkflowDefinition;
  status: WorkflowStatus;
  locked: boolean;
  mayCreate: boolean;
  onRun: (input: WorkflowInput) => void;
}) {
  const [draft, setDraft] = useState<InputDraft>({});
  const [framework, setFramework] = useState<WorkflowFramework | "">("");
  const [example, setExample] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const reported = FRAMEWORKS.filter((name) => status.frameworks[name]);
  const available = reported.filter(
    (name) => status.frameworks[name]?.available,
  );
  const selected =
    framework && available.includes(framework)
      ? framework
      : (available[0] ?? "");
  const browserAvailable =
    !definition.requires_browser ||
    status.frameworks.browser?.available === true;
  function submit(event: FormEvent) {
    event.preventDefault();
    if (
      locked ||
      !mayCreate ||
      !status.enabled ||
      !selected ||
      !browserAvailable
    )
      return;
    try {
      const inputs = parseWorkflowInputs(definition.input_schema, draft);
      setError(null);
      onRun({ workflow_id: definition.id, inputs, framework: selected });
    } catch (error) {
      setError(
        error instanceof Error ? error.message : "Check the workflow inputs.",
      );
    }
  }
  // Without public pages to read, the engine skips its research step.
  const steps = definition.requires_browser
    ? definition.steps
    : definition.steps.filter((step) => step !== "research");
  return (
    <section
      aria-label="Selected workflow"
      className={cn(pageStyles.sheet, "min-w-0 space-y-5 border p-4 sm:p-5")}
    >
      <div className="space-y-1.5">
        <p className={pageStyles.eyebrow}>
          {categoryName(definition.category)}
        </p>
        {/* A catalog entry under the page's "Workflow catalog" h2, titled
            like a run receipt: Nunito, not a second Fraunces heading. */}
        <h3 className="text-lg leading-snug font-bold break-words">
          {definition.title}
        </h3>
        <p className="text-sm leading-relaxed">{definition.summary}</p>
        <p className="text-muted-foreground text-sm">
          {definition.requires_browser
            ? "Reads the public pages you list, then works from them and your inputs."
            : "Works only from the inputs you give it. It reads no web pages."}
        </p>
      </div>
      <div>
        <h4 className={cn(pageStyles.eyebrow, "mb-2")}>
          Checked before it is accepted
        </h4>
        <ul className="ml-5 list-disc space-y-1 text-sm">
          {definition.acceptance.map((check, index) => (
            <li key={index} className="break-words">
              {check}
            </li>
          ))}
        </ul>
        <details className="mt-2">
          <summary className="cursor-pointer py-3 text-sm font-semibold">
            How it runs, in {steps.length} steps
          </summary>
          <ol className="mb-1 ml-5 list-decimal space-y-1 text-sm">
            {steps.map((step, index) => (
              <li key={index} className="break-words">
                {stepName(step)}
              </li>
            ))}
          </ol>
        </details>
      </div>
      <form onSubmit={submit} className="space-y-4 border-t pt-4">
        <p className="text-sm leading-relaxed">
          Give only facts you have checked, and say plainly what you do not
          know. The run adds nothing you did not supply.
        </p>
        <Button
          type="button"
          variant="outline"
          className="min-h-11 max-sm:w-full"
          disabled={locked}
          onClick={() => {
            setDraft(
              exampleDraft(definition.input_schema, definition.example_inputs),
            );
            setExample(true);
            setError(null);
          }}
        >
          Fill in sample inputs
        </Button>
        {example && (
          <p role="status" className="text-muted-foreground text-sm">
            Sample inputs filled in. They describe a made-up business, so
            replace them with your client&apos;s facts before you run.
          </p>
        )}
        {Object.entries(definition.input_schema.properties ?? {}).map(
          ([name, raw]) => {
            const schema = resolvedSchema(raw),
              type = schemaType(schema),
              id = `workflow-input-${name}`,
              required = (definition.input_schema.required ?? []).includes(
                name,
              );
            const label = fieldLabel(name, schema),
              description = fieldHint(schema.description, schema.maxItems);
            const common = {
              id,
              disabled: locked,
              "aria-required": required || undefined,
              "aria-describedby": description ? `${id}-description` : undefined,
            };
            return (
              <div key={name} className="min-w-0 space-y-1.5">
                {type === "boolean" ? (
                  <label
                    htmlFor={id}
                    className="flex min-h-11 items-center gap-3 text-sm"
                  >
                    <input
                      {...common}
                      type="checkbox"
                      checked={draft[name] === true}
                      onChange={(event) =>
                        setDraft((old) => ({
                          ...old,
                          [name]: event.target.checked,
                        }))
                      }
                      className="size-5"
                    />
                    {label}
                  </label>
                ) : (
                  <>
                    <label htmlFor={id} className="block text-sm font-semibold">
                      {label}
                      {required ? (
                        ""
                      ) : (
                        <span className="text-muted-foreground font-normal">
                          {" "}
                          (optional)
                        </span>
                      )}
                    </label>
                    {schema.enum ? (
                      <select
                        {...common}
                        className={CONTROL}
                        value={String(draft[name] ?? "")}
                        onChange={(event) =>
                          setDraft((old) => ({
                            ...old,
                            [name]: event.target.value,
                          }))
                        }
                      >
                        <option value="">Choose one</option>
                        {schema.enum.map((choice) => (
                          <option key={String(choice)} value={String(choice)}>
                            {/^[a-z0-9_]+$/.test(String(choice))
                              ? humanize(String(choice))
                              : String(choice)}
                          </option>
                        ))}
                      </select>
                    ) : type === "number" || type === "integer" ? (
                      <input
                        {...common}
                        type="number"
                        min={schema.minimum}
                        max={schema.maximum}
                        step={type === "integer" ? 1 : "any"}
                        className={CONTROL}
                        value={String(draft[name] ?? "")}
                        onChange={(event) =>
                          setDraft((old) => ({
                            ...old,
                            [name]: event.target.value,
                          }))
                        }
                      />
                    ) : (
                      <textarea
                        {...common}
                        rows={type === "string" ? 3 : 4}
                        maxLength={Math.min(schema.maxLength ?? 32000, 32000)}
                        className={CONTROL}
                        value={String(draft[name] ?? "")}
                        onChange={(event) =>
                          setDraft((old) => ({
                            ...old,
                            [name]: event.target.value,
                          }))
                        }
                        placeholder={
                          type === "array" &&
                          schemaType(schema.items ?? {}) === "string"
                            ? schema.items?.format === "uri"
                              ? "https://"
                              : "One item per line"
                            : type === "object" || type === "array"
                              ? "Written as JSON"
                              : undefined
                        }
                      />
                    )}
                  </>
                )}
                {description && (
                  <p
                    id={`${id}-description`}
                    className="text-muted-foreground text-[0.8125rem] leading-relaxed"
                  >
                    {description}
                  </p>
                )}
              </div>
            );
          },
        )}
        <label
          htmlFor="workflow-framework"
          className="block text-sm font-semibold"
        >
          Runs on
        </label>
        <select
          id="workflow-framework"
          className={CONTROL}
          disabled={locked}
          value={selected}
          onChange={(event) =>
            setFramework(event.target.value as WorkflowFramework)
          }
        >
          {!selected && <option value="">No framework available</option>}
          {reported.map((name) => (
            <option
              key={name}
              value={name}
              disabled={!status.frameworks[name]?.available}
            >
              {FRAMEWORK_LABELS[name]}
              {status.frameworks[name]?.available ? "" : " (not set up)"}
            </option>
          ))}
        </select>
        <p className="text-muted-foreground text-[0.8125rem] leading-relaxed">
          A run makes at most {status.limits.max_model_calls_per_run} model
          calls and writes at most{" "}
          {status.limits.max_output_tokens_per_run.toLocaleString()} tokens,
          billed to your model provider account.
        </p>
        {!mayCreate && (
          <p className="text-sm">
            You can read workflows here, but running them needs more access.
          </p>
        )}
        {!status.enabled && (
          <p className="text-sm">
            Workflow runs are turned off in this workspace.
          </p>
        )}
        {!browserAvailable && (
          <p className="text-sm">
            This workflow reads public pages, and page capture is not set up
            here
            {status.frameworks.browser?.detail
              ? `: ${status.frameworks.browser.detail}`
              : ""}
            .
          </p>
        )}
        {error && (
          <p role="alert" className="text-destructive text-sm">
            {error}
          </p>
        )}
        <Button
          type="submit"
          className="min-h-11 max-sm:w-full"
          disabled={
            locked ||
            !mayCreate ||
            !status.enabled ||
            !selected ||
            !browserAvailable
          }
        >
          {locked ? "Request held" : "Run workflow"}
        </Button>
      </form>
    </section>
  );
}
