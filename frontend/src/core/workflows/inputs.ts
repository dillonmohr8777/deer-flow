import { publicResearchUrl } from "@/core/browserbase/urls";

import { type InputSchema } from "./types";

export type InputDraft = Record<string, string | boolean>;
export const MAX_INPUT_BYTES = 48_000;
export function resolvedSchema(schema: InputSchema): InputSchema {
  return schema.anyOf?.find((entry) => entry.type !== "null") ?? schema;
}
export function schemaType(schema: InputSchema): string {
  const type = resolvedSchema(schema).type;
  return Array.isArray(type)
    ? (type.find((value) => value !== "null") ?? "string")
    : (type ?? "string");
}
// Words a snake_case field name loses when it is only capitalised.
const LABEL_WORDS: Record<string, string> = {
  url: "URL",
  urls: "URLs",
  kpis: "KPIs",
  seo: "SEO",
  a11y: "accessibility",
};
export function fieldLabel(name: string, schema: InputSchema): string {
  return (
    schema.title ??
    name
      .split("_")
      .map((word) => LABEL_WORDS[word] ?? word)
      .join(" ")
      .replace(/^./, (letter) => letter.toUpperCase())
  );
}
export function exampleDraft(
  schema: InputSchema,
  values: Record<string, unknown>,
): InputDraft {
  return Object.fromEntries(
    Object.entries(schema.properties ?? {}).map(([name, raw]) => {
      const field = resolvedSchema(raw),
        value = values[name];
      const type = schemaType(field);
      return [
        name,
        type === "boolean"
          ? value === true
          : value === undefined || value === null
            ? ""
            : type === "array" &&
                schemaType(field.items ?? {}) === "string" &&
                Array.isArray(value)
              ? value
                  .map((entry: unknown) =>
                    typeof entry === "string" ? entry : JSON.stringify(entry),
                  )
                  .join("\n")
              : typeof value === "object"
                ? JSON.stringify(value, null, 2)
                : typeof value === "string"
                  ? value
                  : typeof value === "number" || typeof value === "boolean"
                    ? String(value)
                    : "",
      ];
    }),
  );
}
function validate(
  field: InputSchema,
  value: unknown,
  label: string,
  depth = 0,
): void {
  if (depth > 8) throw new Error(`${label} is nested too deeply.`);
  const schema = resolvedSchema(field),
    type = schemaType(schema);
  if (schema.enum && !schema.enum.includes(value))
    throw new Error(`${label} must use one of the available choices.`);
  if (type === "string") {
    if (typeof value !== "string") throw new Error(`${label} must be text.`);
    const length = [...value].length;
    if (
      length < (schema.minLength ?? 0) ||
      length > Math.min(schema.maxLength ?? 32000, 32000)
    )
      throw new Error(`${label} has an invalid text length.`);
  } else if (type === "number" || type === "integer") {
    if (
      typeof value !== "number" ||
      !Number.isFinite(value) ||
      (type === "integer" && !Number.isInteger(value)) ||
      value < (schema.minimum ?? -Infinity) ||
      value > (schema.maximum ?? Infinity)
    )
      throw new Error(`${label} must be a number within its allowed bounds.`);
  } else if (type === "boolean") {
    if (typeof value !== "boolean")
      throw new Error(`${label} must be true or false.`);
  } else if (type === "array") {
    if (
      !Array.isArray(value) ||
      value.length < (schema.minItems ?? 0) ||
      value.length > Math.min(schema.maxItems ?? 100, 100)
    )
      throw new Error(`${label} has an invalid number of items.`);
    value.forEach((entry) =>
      validate(schema.items ?? {}, entry, label, depth + 1),
    );
  } else if (type === "object") {
    if (!value || typeof value !== "object" || Array.isArray(value))
      throw new Error(`${label} must be a JSON object.`);
    const entries = value as Record<string, unknown>;
    for (const name of schema.required ?? [])
      if (!(name in entries)) throw new Error(`${label}: ${name} is required.`);
    for (const [name, entry] of Object.entries(entries)) {
      if (schema.properties?.[name])
        validate(
          schema.properties[name],
          entry,
          `${label}: ${name}`,
          depth + 1,
        );
      else if (schema.additionalProperties === false)
        throw new Error(`${label}: ${name} is not allowed.`);
    }
  }
}
export function parseWorkflowInputs(
  schema: InputSchema,
  draft: InputDraft,
): Record<string, unknown> {
  const values: Record<string, unknown> = {};
  for (const [name, raw] of Object.entries(schema.properties ?? {})) {
    if (!(name in draft) && !(schema.required ?? []).includes(name)) continue;
    const field = resolvedSchema(raw),
      label = fieldLabel(name, field),
      type = schemaType(field),
      text = draft[name] ?? (type === "boolean" ? false : "");
    if (text === "" && !(schema.required ?? []).includes(name)) continue;
    if (text === "") throw new Error(`${label} is required.`);
    let value: unknown = text;
    if (type === "number" || type === "integer") value = Number(text);
    else if (type === "array" && schemaType(field.items ?? {}) === "string")
      value = String(text)
        .split(/\r?\n/)
        .map((entry) => entry.trim())
        .filter(Boolean);
    else if (type === "array" || type === "object") {
      try {
        value = JSON.parse(String(text));
      } catch {
        throw new Error(`${label} must contain valid JSON.`);
      }
    }
    validate(field, value, label);
    if (name === "source_urls" && Array.isArray(value)) {
      const urls = value.map((url) => publicResearchUrl(String(url)));
      if (urls.some((url) => url === null))
        throw new Error(
          "Source URLs must be public HTTPS pages without credentials or a custom port.",
        );
      if (new Set(urls).size !== urls.length)
        throw new Error("Each source URL must be different.");
      value = urls;
    }
    values[name] = value;
  }
  if (new TextEncoder().encode(JSON.stringify(values)).length > MAX_INPUT_BYTES)
    throw new Error("The workflow inputs exceed the 48 KB limit.");
  return values;
}
