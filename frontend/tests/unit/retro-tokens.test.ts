import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "@rstest/core";

// Mirrors tests/unit/paper-tokens.test.ts.
const cssPath = join(__dirname, "..", "..", "src", "styles", "retro.css");
const css = readFileSync(cssPath, "utf8");

function parseTokens(source: string): Record<string, string> {
  const tokens: Record<string, string> = {};
  const re = /--(retro-[\w-]+):\s*#([0-9a-fA-F]{6})\s*;/g;
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
  if (!value) throw new Error(`retro.css is missing token --${name}`);
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

describe("retro token palette (WCAG contrast)", () => {
  it("declares every token the spec table names", () => {
    for (const name of [
      "retro-navy",
      "retro-navy-hi",
      "retro-cream",
      "retro-cream-muted",
      "retro-amber",
      "retro-amber-deep",
      "retro-danger",
      "retro-ok",
    ]) {
      expect(tokens[name]).toBeDefined();
    }
  });

  it("keeps the core identity palette to navy, cream and one warm accent", () => {
    // Semantic status colors (danger/ok) sit outside this check, same as
    // paper.css's canon list documents danger/ok separately from "blue,
    // white, grey, gold". The identity palette — canvas, panel, text, the
    // one accent and its object-only border — must read as navy or warm.
    for (const name of [
      "retro-navy",
      "retro-navy-hi",
      "retro-cream",
      "retro-cream-muted",
      "retro-amber",
      "retro-amber-deep",
    ]) {
      const [r, g, b] = hexToRgb(requireToken(name));
      const navy = b >= r && b >= g;
      const warm = r >= b && g >= b * 0.5;
      expect(navy || warm, `${name} is outside the limited palette`).toBe(
        true,
      );
    }
  });

  const pairings: Array<[string, string, string, number]> = [
    ["retro-cream", "retro-navy", "cream vs navy", 14.95],
    ["retro-cream-muted", "retro-navy", "cream-muted vs navy", 9.45],
    ["retro-amber", "retro-navy", "amber vs navy", 8.05],
    ["retro-danger", "retro-navy", "danger vs navy", 5.54],
    ["retro-ok", "retro-navy", "ok vs navy", 9.6],
  ];

  it.each(pairings)(
    "%s / %s (%s) meets 4.5:1 and its measured ratio of %f",
    (a, b, _label, minRatio) => {
      const ratio = contrastRatio(requireToken(a), requireToken(b));
      expect(ratio).toBeGreaterThanOrEqual(4.5);
      expect(ratio).toBeGreaterThanOrEqual(minRatio - EPSILON);
    },
  );

  it("keeps the object-only amber-deep border below text-safe contrast on cream", () => {
    const ratio = contrastRatio(
      requireToken("retro-amber-deep"),
      requireToken("retro-cream"),
    );
    expect(ratio).toBeLessThan(4.5);
  });
});
