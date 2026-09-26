import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "@rstest/core";

type Treatment = "space" | "retro";

function stylesheet(treatment: Treatment): string {
  return readFileSync(
    join(__dirname, "..", "..", "src", "styles", `${treatment}.css`),
    "utf8",
  );
}

function token(css: string, name: string): string {
  const match = new RegExp(`--${name}:\\s*(#[0-9a-f]{6})\\s*;`, "i").exec(css);
  if (!match?.[1]) throw new Error(`Missing color token --${name}`);
  return match[1];
}

function luminance(hex: string): number {
  const rgb = [1, 3, 5].map(
    (offset) => Number.parseInt(hex.slice(offset, offset + 2), 16) / 255,
  );
  const linear = rgb.map((value) =>
    value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4,
  );
  return linear[0]! * 0.2126 + linear[1]! * 0.7152 + linear[2]! * 0.0722;
}

function contrast(foreground: string, background: string): number {
  const values = [luminance(foreground), luminance(background)].sort(
    (a, b) => b - a,
  );
  return (values[0]! + 0.05) / (values[1]! + 0.05);
}

describe.each([
  ["space", "space-void"],
  ["retro", "retro-navy"],
] as const)("%s generated response contrast", (treatment, backgroundName) => {
  const css = stylesheet(treatment);
  const copyRule = /\.momentum-generated-copy\s*\{([^}]+)\}/.exec(css)?.[1];

  it("scopes a readable generated-copy palette to the treatment", () => {
    expect(css).toContain(`:root:not(.dark)[data-treatment="${treatment}"]`);
    expect(css).toContain(
      `[data-workspace-shell][data-treatment="${treatment}"]`,
    );
    expect(copyRule).toBeDefined();

    const background = token(css, backgroundName);
    for (const role of [
      "body",
      "heading",
      "heading-from",
      "heading-mid",
      "heading-to",
      "strong",
      "link",
      "marker",
      "quote",
      "code",
    ]) {
      const match = new RegExp(
        `--momentum-copy-${role}:\\s*var\\(--([\\w-]+)\\)\\s*;`,
      ).exec(copyRule ?? "");
      expect(match?.[1], `${role} is missing a treatment color`).toBeDefined();
      expect(
        contrast(token(css, match![1]!), background),
        `${role} should be readable on the dark chat canvas`,
      ).toBeGreaterThanOrEqual(4.5);
    }
  });
});
