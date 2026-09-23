import { describe, expect, it } from "@rstest/core";

import {
  formatModelLabel,
  modelDisplayName,
} from "@/components/workspace/command-center/model-label";

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

  it("recovers the model from namespaced and doubled provider IDs", () => {
    // Usage and ledger rows currently arrive concatenated twice.
    expect(
      formatModelLabel(
        "meta/muse-spark-1.3-contributormeta/muse-spark-1.3-contributor",
      ),
    ).toBe("Muse Spark 1.3");
    expect(formatModelLabel("deepseek/deepseek-v4-flash")).toBe(
      "DeepSeek V4 Flash",
    );
    expect(formatModelLabel("google/gemini-3.8-flash")).toBe(
      "Gemini 3.8 Flash",
    );
  });

  it("drops a tier word wherever it sits, not only at the end", () => {
    expect(formatModelLabel("openrouter-contributor-edition-2")).toBe(
      "Edition 2",
    );
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

describe("modelDisplayName", () => {
  const models = [
    {
      name: "openrouter-muse-spark-contributor",
      display_name: "Muse Spark 1.3 Contributor (OpenRouter)",
    },
    { name: "openrouter-luna", display_name: "GPT 5.6 Luna (OpenRouter)" },
    { name: "ollama-qwen3.5-27b", display_name: "Qwen 3.5 27B (Local)" },
  ];

  it("uses the configured name without the provider or the tier word", () => {
    expect(modelDisplayName("openrouter-muse-spark-contributor", models)).toBe(
      "Muse Spark 1.3",
    );
    expect(modelDisplayName("openrouter-luna", models)).toBe("GPT 5.6 Luna");
    expect(modelDisplayName("ollama-qwen3.5-27b", models)).toBe("Qwen 3.5 27B");
  });

  it("falls back to the slug formatter for models the list does not know", () => {
    expect(modelDisplayName("google/gemini-3.8-flash", models)).toBe(
      "Gemini 3.8 Flash",
    );
    expect(modelDisplayName("openrouter-sonnet-5")).toBe("Claude Sonnet 5");
    expect(modelDisplayName(null, models)).toBe("");
  });
});
