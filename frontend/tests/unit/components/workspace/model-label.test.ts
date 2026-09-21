import { describe, expect, it } from "@rstest/core";

import { formatModelLabel } from "@/components/workspace/command-center/model-label";

describe("formatModelLabel", () => {
  it("never exposes the Contributor tier", () => {
    // The standing product rule: Contributor tier is never advertised
    // publicly. This is the assertion that must never be deleted.
    const out = formatModelLabel("openrouter-muse-spark-contributor");
    expect(out.toLowerCase()).not.toContain("contributor");
    expect(out).toBe("Muse Spark 1.3");
  });

  it("strips tier markers even on slugs we have never seen", () => {
    for (const slug of [
      "openrouter-something-new-contributor",
      "vercel-whatever:batch",
      "openrouter-model-preview",
    ]) {
      expect(formatModelLabel(slug).toLowerCase()).not.toMatch(
        /contributor|batch|preview/,
      );
    }
  });

  it("strips provider routing prefixes", () => {
    expect(formatModelLabel("openrouter-opus-5")).toBe("Claude Opus 5");
    expect(formatModelLabel("openrouter-sonnet-5")).toBe("Claude Sonnet 5");
    expect(formatModelLabel("openrouter-fable-5.1")).toBe("Claude Fable 5.1");
    expect(formatModelLabel("anthropic/claude-opus-5")).toBe("Claude Opus 5");
  });

  it("keeps the inherit affordance", () => {
    expect(formatModelLabel("inherit")).toBe("Lead model");
  });

  it("degrades gracefully rather than leaking the raw slug", () => {
    // An unknown model must still read as a name, not routing plumbing.
    expect(formatModelLabel("openrouter-brand-new-model")).toBe(
      "Brand New Model",
    );
    expect(formatModelLabel("")).toBe("");
    expect(formatModelLabel(null)).toBe("");
    expect(formatModelLabel(undefined)).toBe("");
  });

  it("never returns a string containing a slash or provider prefix", () => {
    for (const slug of [
      "openrouter-opus-5",
      "anthropic/claude-sonnet-5",
      "ollama-qwen3-coder-30b",
      "vercel-gemini-3.8-flash",
    ]) {
      const out = formatModelLabel(slug);
      expect(out).not.toContain("/");
      expect(out).not.toMatch(/^(openrouter|vercel|ollama|gateway)-/);
    }
  });
});
