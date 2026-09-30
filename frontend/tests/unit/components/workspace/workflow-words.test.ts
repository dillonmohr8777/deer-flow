import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "@rstest/core";

import {
  UNKNOWN_CODE_SENTENCE,
  explanation,
} from "@/components/workspace/workflows/workflow-words";

const repoRoot = join(import.meta.dirname, "../../../../..");

/** Every code a stored run can carry, read from the backend raise sites. */
function raisedCodes(): string[] {
  const workflows = "backend/packages/harness/deerflow/workflows";
  const sources = [
    `${workflows}/engine.py`,
    `${workflows}/catalog.py`,
    "backend/app/gateway/workflow_service.py",
  ].map((path) => readFileSync(join(repoRoot, path), "utf8"));
  // Only WorkflowError subclasses and WorkflowServiceError carry a `code` the
  // service stores; a bare ValueError/RuntimeError is stored as
  // workflow_execution_failed.
  const raise = /(Workflow\w*Error)\(\s*"([a-z0-9_]+)"/g;
  const codes = new Set<string>();
  for (const source of sources)
    for (const match of source.matchAll(raise)) codes.add(match[2]!);
  return [...codes].sort();
}

describe("workflow error words", () => {
  it("finds the engine's own codes at their raise sites", () => {
    const codes = raisedCodes();
    expect(codes).toContain("workflow_independent_review_rejected");
    expect(codes).toContain("workflow_model_call_failed");
    expect(codes).toContain("resume_limit");
    expect(codes.length).toBeGreaterThan(50);
  });

  it("puts every raised code into words, never the generic sentence", () => {
    const missing = raisedCodes().filter(
      (code) => explanation(new Error(code)) === UNKNOWN_CODE_SENTENCE,
    );
    expect(missing).toEqual([]);
  });

  it("tells a rejected review, a failed model call and a call limit apart", () => {
    const words = [
      "workflow_independent_review_rejected",
      "workflow_model_call_failed",
      "workflow_call_limit_exceeded",
      "workflow_context_too_large",
      "workflow_browser_evidence_missing",
      "acceptance_failed",
      "run_token_budget_exhausted",
    ].map((code) => explanation(new Error(code)));
    expect(new Set(words).size).toBe(words.length);
    for (const sentence of words) expect(sentence).not.toMatch(/_/);
  });

  it("keeps a sentence from the server and hides an unknown code", () => {
    expect(explanation(new Error("Model-call budget reached."))).toBe(
      "Model-call budget reached.",
    );
    expect(explanation(new Error("some_internal_code"))).toBe(
      UNKNOWN_CODE_SENTENCE,
    );
  });
});
