import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "@rstest/core";

// Reads the real stylesheet — this test is the proof for the palette, not a
// second copy of it. Mirrors tests/unit/paper-tokens.test.ts.
const cssPath = join(__dirname, "..", "..", "src", "styles", "space.css");
const css = readFileSync(cssPath, "utf8");

function parseTokens(source: string): Record<string, string> {
  const tokens: Record<string, string> = {};
  const re = /--(space-[\w-]+):\s*#([0-9a-fA-F]{6})\s*;/g;
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
  if (!value) throw new Error(`space.css is missing token --${name}`);
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

describe("space token palette (WCAG contrast)", () => {
  it("declares every token the spec table names", () => {
    for (const name of [
      "space-void",
      "space-panel",
      "space-panel-hi",
      "space-cream",
      "space-cream-muted",
      "space-cyan",
      "space-line",
      "space-focus",
      "space-danger",
      "space-ok",
    ]) {
      expect(tokens[name]).toBeDefined();
    }
  });

  // Every pairing here is a real text/background combination used by
  // space.css's shell remap: body text on the canvas, panel text, and each
  // semantic accent used as text on the void canvas.
  const pairings: Array<[string, string, string, number]> = [
    ["space-cream", "space-void", "cream vs void", 16.88],
    ["space-panel", "space-cream", "panel vs cream", 15.27],
    ["space-panel-hi", "space-cream", "panel-hi vs cream", 14.22],
    ["space-cream-muted", "space-void", "cream-muted vs void", 11.59],
    ["space-cyan", "space-void", "cyan vs void", 12.86],
    ["space-focus", "space-void", "focus vs void", 13.87],
    ["space-danger", "space-void", "danger vs void", 9.34],
    ["space-ok", "space-void", "ok vs void", 12.81],
  ];

  it.each(pairings)(
    "%s / %s (%s) meets 4.5:1 and its measured ratio of %f",
    (a, b, _label, minRatio) => {
      const ratio = contrastRatio(requireToken(a), requireToken(b));
      expect(ratio).toBeGreaterThanOrEqual(4.5);
      expect(ratio).toBeGreaterThanOrEqual(minRatio - EPSILON);
    },
  );

  it("keeps every declared hex distinct from purple/violet hues", () => {
    // A crude but effective guard: none of the declared colours may have a
    // blue channel that dominates both red and green by a violet-typical
    // margin while red also runs high (the "AI purple" signature).
    for (const [name, hex] of Object.entries(tokens)) {
      const [r, g, b] = hexToRgb(hex);
      const looksPurple = b > g + 24 && r > g + 8;
      expect(looksPurple, `${name} (${hex}) reads as purple/violet`).toBe(
        false,
      );
    }
  });
});
