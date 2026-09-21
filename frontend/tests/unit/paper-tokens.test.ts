import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "@rstest/core";

// Reads the real stylesheet — this test is the proof for the palette, not a
// second copy of it. If someone edits a hex in paper.css without checking
// contrast, this is what catches it.
const paperCssPath = join(
  __dirname,
  "..",
  "..",
  "src",
  "styles",
  "paper.css",
);
const paperCss = readFileSync(paperCssPath, "utf8");

/** Parses every `--paper-<name>: #rrggbb;` declaration out of paper.css. */
function parseTokens(css: string): Record<string, string> {
  const tokens: Record<string, string> = {};
  const re = /--(paper-[\w-]+):\s*#([0-9a-fA-F]{6})\s*;/g;
  let match: RegExpExecArray | null;
  while ((match = re.exec(css))) {
    const [, name, hex] = match;
    if (name && hex) tokens[name] = `#${hex}`;
  }
  return tokens;
}

const tokens = parseTokens(paperCss);

/** Looks up a token, failing loudly (not silently) if paper.css dropped it. */
function requireToken(name: string): string {
  const value = tokens[name];
  if (!value) throw new Error(`paper.css is missing token --${name}`);
  return value;
}

function hexToRgb(hex: string): [number, number, number] {
  const n = Number.parseInt(hex.slice(1), 16);
  return [(n >> 16) & 0xff, (n >> 8) & 0xff, n & 0xff];
}

/** WCAG relative luminance. */
function relativeLuminance([r, g, b]: [number, number, number]): number {
  const channel = (c: number) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  const [rl, gl, bl] = [channel(r), channel(g), channel(b)];
  return 0.2126 * rl + 0.7152 * gl + 0.0722 * bl;
}

/** WCAG contrast ratio between two hex colours, 1..21. */
function contrastRatio(hexA: string, hexB: string): number {
  const lumA = relativeLuminance(hexToRgb(hexA));
  const lumB = relativeLuminance(hexToRgb(hexB));
  const [lighter, darker] = lumA >= lumB ? [lumA, lumB] : [lumB, lumA];
  return (lighter + 0.05) / (darker + 0.05);
}

// Tolerance for the stated table's rounding, not for missing the bar.
const EPSILON = 0.02;

describe("paper token palette (WCAG contrast)", () => {
  it("declares every token the spec table names", () => {
    for (const name of [
      "paper-cream",
      "paper-cream-hi",
      "paper-kraft",
      "paper-royal",
      "paper-royal-deep",
      "paper-ink",
      "paper-ink-muted",
      "paper-brass-text",
      "paper-cyan-text",
      "paper-line",
      "paper-focus",
      "paper-danger",
      "paper-ok",
      "paper-brass",
      "paper-cyan",
    ]) {
      expect(tokens[name]).toBeDefined();
    }
  });

  const pairings: Array<[string, string, string, number]> = [
    ["paper-cream", "paper-ink", "cream vs ink", 14.07],
    ["paper-cream-hi", "paper-ink", "cream-hi vs ink", 15.47],
    ["paper-kraft", "paper-ink", "kraft vs ink", 9.56],
    ["paper-royal", "paper-cream", "royal on cream", 7.07],
    // The spec table rounds this pairing to 10.49; the precise WCAG figure
    // for the approved hexes (#F2EDE3 on #14346E) is ~10.31 — still AAA for
    // normal text (>=7), so the palette is fine, the table's digit is just
    // slightly off. Asserted against the true computed value, not the typo.
    ["paper-royal-deep", "paper-cream", "cream-ink on royal-deep", 10.3],
    ["paper-ink-muted", "paper-cream", "ink-muted on cream", 7.59],
    ["paper-brass-text", "paper-cream", "brass-text on cream", 5.23],
    ["paper-cyan-text", "paper-cream", "cyan-text on cream", 5.9],
    ["paper-line", "paper-cream", "line on cream (UI, not text)", 3.56],
    ["paper-focus", "paper-cream", "focus on cream", 8.14],
    ["paper-danger", "paper-cream", "danger on cream", 6.46],
    ["paper-ok", "paper-cream", "ok on cream", 5.57],
  ];

  it.each(pairings)(
    "%s / %s (%s) meets its approved ratio of %f",
    (a, b, _label, minRatio) => {
      const ratio = contrastRatio(requireToken(a), requireToken(b));
      expect(ratio).toBeGreaterThanOrEqual(minRatio - EPSILON);
    },
  );

  it("keeps the object-only accents (brass, cyan) below text-safe contrast on cream", () => {
    // These are documented as object-only precisely because they fail as
    // text. If a future edit accidentally makes them text-safe, that's a
    // sign the hex changed underneath the -text variant's promise.
    const brassRatio = contrastRatio(
      requireToken("paper-brass"),
      requireToken("paper-cream"),
    );
    const cyanRatio = contrastRatio(
      requireToken("paper-cyan"),
      requireToken("paper-cream"),
    );
    expect(brassRatio).toBeLessThan(4.5);
    expect(cyanRatio).toBeLessThan(4.5);
  });

  it("never uses the object-only brass or cyan tokens as a text color", () => {
    // Any `color:` (or color-mix feeding one) built directly from the
    // object-only tokens would silently produce unreadable text. Only the
    // -text variants may appear on a color property.
    const colorDeclarations = paperCss.match(/color\s*:[^;]+;/g) ?? [];
    for (const declaration of colorDeclarations) {
      expect(declaration).not.toMatch(/--paper-brass\b(?!-text)/);
      expect(declaration).not.toMatch(/--paper-cyan\b(?!-text)/);
    }
  });
});
