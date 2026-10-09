import { describe, expect, it } from "@rstest/core";

import { exampleDraft, parseWorkflowInputs } from "@/core/workflows/inputs";

import { WORKFLOW_FIXTURES } from "../../../fixtures/workflows";

const schema = WORKFLOW_FIXTURES[0]!.input_schema;
describe("Workflow schema input feedback", () => {
  it("keeps all100 synthetic definitions independently editable without auto-dispatch", () => {
    expect(
      new Set(WORKFLOW_FIXTURES.map((definition) => definition.id)).size,
    ).toBe(100);
    for (const definition of WORKFLOW_FIXTURES) {
      const values = parseWorkflowInputs(
        definition.input_schema,
        exampleDraft(definition.input_schema, definition.example_inputs),
      );
      expect(values.brief).toContain("Synthetic");
      expect(values.source_urls).toEqual(["https://example.com/"]);
    }
  });
  it("requires declared fields and bounds numeric, string and array inputs", () => {
    expect(() => parseWorkflowInputs(schema, {})).toThrow("required");
    expect(() =>
      parseWorkflowInputs(schema, { brief: "a".repeat(1001) }),
    ).toThrow("length");
    expect(() =>
      parseWorkflowInputs(schema, { brief: "Task", count: "1.5" }),
    ).toThrow("bounds");
    expect(() =>
      parseWorkflowInputs(schema, {
        brief: "Task",
        source_urls:
          "https://example.com\nhttps://openai.com\nhttps://example.org\nhttps://example.net",
      }),
    ).toThrow("items");
  });
  it("parses JSON objects and rejects malformed or undeclared nested fields", () => {
    expect(
      parseWorkflowInputs(schema, {
        brief: "Task",
        context: '{"audience":"Operators"}',
      }).context,
    ).toEqual({ audience: "Operators" });
    expect(() =>
      parseWorkflowInputs(schema, { brief: "Task", context: "{" }),
    ).toThrow("valid JSON");
    expect(() =>
      parseWorkflowInputs(schema, {
        brief: "Task",
        context: '{"secret":"private"}',
      }),
    ).toThrow("not allowed");
  });
  it("rejects unsafe or duplicate browser source inputs before dispatch", () => {
    for (const url of [
      "https://localhost",
      "http://example.com",
      "https://me:secret@example.com",
    ])
      expect(() =>
        parseWorkflowInputs(schema, { brief: "Task", source_urls: url }),
      ).toThrow("public HTTPS");
    expect(() =>
      parseWorkflowInputs(schema, {
        brief: "Task",
        source_urls: "https://example.com\nhttps://example.com/",
      }),
    ).toThrow("different");
  });
  it("preserves explicit false and omits untouched optional inputs", () => {
    expect(
      parseWorkflowInputs(schema, { brief: "Task", include_notes: false }),
    ).toEqual({ brief: "Task", include_notes: false });
  });
  it("bounds the entire UTF-8 input body before dispatch", () => {
    const bounded = {
      type: "object",
      properties: Object.fromEntries(
        Array.from({ length: 8 }, (_, index) => [
          `field_${index}`,
          { type: "string", maxLength: 6000 },
        ]),
      ),
    };
    const draft = Object.fromEntries(
      Array.from({ length: 8 }, (_, index) => [
        `field_${index}`,
        "a".repeat(6000),
      ]),
    );
    expect(() => parseWorkflowInputs(bounded, draft)).toThrow("48 KB");
    expect(() =>
      parseWorkflowInputs(
        { type: "object", properties: { brief: { type: "string" } } },
        { brief: "🙂".repeat(12_000) },
      ),
    ).toThrow("48 KB");
  });
});
