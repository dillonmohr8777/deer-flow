"use client";

import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
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
  return (
    <section aria-label="Selected workflow" className="min-w-0 space-y-5">
      <div className="space-y-2">
        <p className="text-muted-foreground text-sm">
          {definition.category} ·{" "}
          {definition.requires_browser
            ? "Public browser evidence required"
            : "Model workflow"}
        </p>
        <h2 className="text-xl break-words">{definition.title}</h2>
        <p className="text-sm leading-relaxed">{definition.summary}</p>
      </div>
      <details className="rounded-md border p-3">
        <summary className="min-h-11 cursor-pointer py-2 text-sm">
          Steps and acceptance checks
        </summary>
        <ol className="ml-5 list-decimal space-y-1 text-sm">
          {definition.steps.map((step, index) => (
            <li key={index} className="break-words">
              {step}
            </li>
          ))}
        </ol>
        <ul className="mt-3 ml-5 list-disc space-y-1 text-sm">
          {definition.acceptance.map((check, index) => (
            <li key={index} className="break-words">
              {check}
            </li>
          ))}
        </ul>
      </details>
      <form onSubmit={submit} className="space-y-4">
        <Button
          type="button"
          variant="outline"
          className="min-h-11"
          disabled={locked}
          onClick={() => {
            setDraft(
              exampleDraft(definition.input_schema, definition.example_inputs),
            );
            setExample(true);
            setError(null);
          }}
        >
          Load synthetic example
        </Button>
        {example && (
          <p role="status" className="text-muted-foreground text-sm">
            Synthetic example loaded. Edit these inputs for your actual task
            before running.
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
              description = schema.description;
            const common = {
              id,
              disabled: locked,
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
                    <label htmlFor={id} className="block text-sm">
                      {label}
                      {required ? " (required)" : ""}
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
                        <option value="">Choose…</option>
                        {schema.enum.map((choice) => (
                          <option key={String(choice)} value={String(choice)}>
                            {String(choice)}
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
                            ? "One item per line"
                            : type === "object" || type === "array"
                              ? "Enter bounded JSON"
                              : undefined
                        }
                      />
                    )}
                  </>
                )}
                {description && (
                  <p
                    id={`${id}-description`}
                    className="text-muted-foreground text-xs leading-relaxed"
                  >
                    {description}
                  </p>
                )}
              </div>
            );
          },
        )}
        <label htmlFor="workflow-framework" className="block text-sm">
          Execution framework
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
              {status.frameworks[name]?.available ? "" : " (unavailable)"}
            </option>
          ))}
        </select>
        <p className="text-muted-foreground text-xs leading-relaxed">
          Each run is bounded to {status.limits.max_model_calls_per_run} model
          calls and {status.limits.max_output_tokens_per_run.toLocaleString()}{" "}
          output tokens. Execution uses your configured provider account.
        </p>
        {!mayCreate && <p className="text-sm">You have read-only access.</p>}
        {!status.enabled && (
          <p className="text-sm">Workflow execution is disabled.</p>
        )}
        {!browserAvailable && (
          <p className="text-sm">
            Public browser evidence is unavailable:{" "}
            {status.frameworks.browser?.detail ?? "capability not reported"}.
          </p>
        )}
        {error && (
          <p role="alert" className="text-destructive text-sm">
            {error}
          </p>
        )}
        <Button
          type="submit"
          className="min-h-11"
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
