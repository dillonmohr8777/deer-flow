import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "@rstest/core";

// Mirrors tests/unit/paper-tokens.test.ts.
const cssPath = join(__dirname, "..", "..", "src", "styles", "future.css");
const css = readFileSync(cssPath, "utf8");

function parseTokens(source: string): Record<string, string> {
  const tokens: Record<string, string> = {};
  const re = /--(future-[\w-]+):\s*#([0-9a-fA-F]{6})\s*;/g;
  let match: RegExpExecArray | null;
  while ((match = re.exec(source))) {
    const [, name, hex] = match;
    if (name && hex) tokens[name] = `#${hex}`;
  }
  return tokens;
}

const tokens = parseTokens(css);

function requireToken(name: string): string {
  const value = tokens[name];
  if (!value) throw new Error(`future.css is missing token --${name}`);
  return value;
}

function hexToRgb(hex: string): [number, number, number] {
  const n = Number.parseInt(hex.slice(1), 16);
  return [(n >> 16) & 0xff, (n >> 8) & 0xff, n & 0xff];
}

function relativeLuminance([r, g, b]: [number, number, number]): number {
  const channel = (c: number) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  const [rl, gl, bl] = [channel(r), channel(g), channel(b)];
  return 0.2126 * rl + 0.7152 * gl + 0.0722 * bl;
}

function contrastRatio(hexA: string, hexB: string): number {
  const lumA = relativeLuminance(hexToRgb(hexA));
  const lumB = relativeLuminance(hexToRgb(hexB));
  const [lighter, darker] = lumA >= lumB ? [lumA, lumB] : [lumB, lumA];
  return (lighter + 0.05) / (darker + 0.05);
}

const EPSILON = 0.02;

describe("future token palette (WCAG contrast)", () => {
  it("declares every token the spec table names", () => {
    for (const name of [
      "future-white",
      "future-silver",
      "future-graphite",
      "future-graphite-lo",
      "future-accent",
      "future-focus",
      "future-danger",
      "future-ok",
      "future-chrome-deep",
    ]) {
      expect(tokens[name]).toBeDefined();
    }
  });

  const pairings: Array<[string, string, string, number]> = [
    ["future-graphite", "future-white", "graphite vs white", 15.17],
    ["future-graphite-lo", "future-white", "graphite-lo vs white", 7.98],
    ["future-accent", "future-white", "accent vs white", 6.57],
    ["future-focus", "future-white", "focus vs white", 6.57],
    ["future-danger", "future-white", "danger vs white", 6.54],
    ["future-ok", "future-white", "ok vs white", 5.39],
  ];

  it.each(pairings)(
    "%s / %s (%s) meets 4.5:1 and its measured ratio of %f",
    (a, b, _label, minRatio) => {
      const ratio = contrastRatio(requireToken(a), requireToken(b));
      expect(ratio).toBeGreaterThanOrEqual(4.5);
      expect(ratio).toBeGreaterThanOrEqual(minRatio - EPSILON);
    },
  );

  it("keeps the object-only chrome-deep stop below text-safe contrast on white", () => {
    // Documented object-only: the brushed-chrome gradient's dark stop, never
    // a text color. If a future edit made it text-safe by accident, that's a
    // sign the hex moved out from under the "large surfaces only" promise.
    const ratio = contrastRatio(
      requireToken("future-chrome-deep"),
      requireToken("future-white"),
    );
    expect(ratio).toBeLessThan(4.5);
  });

  it("never uses the object-only chrome-deep token as a text color", () => {
    const colorDeclarations = css.match(/color\s*:[^;]+;/g) ?? [];
    for (const declaration of colorDeclarations) {
      expect(declaration).not.toMatch(/--future-chrome-deep\b/);
    }
  });
});
