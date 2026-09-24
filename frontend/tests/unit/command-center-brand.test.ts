import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "@rstest/core";

// Owner decision 2026-09-22: brand tokens only, no AI purple on the primary
// action or the lead-agent card. Reads the real stylesheet.
const css = readFileSync(
  join(
    __dirname,
    "..",
    "..",
    "src",
    "components",
    "workspace",
    "command-center",
    "command-center.module.css",
  ),
  "utf8",
);

function rule(selector: string): string {
  const start = css.indexOf(`\n${selector} {`);
  expect(start).toBeGreaterThan(-1);
  return css.slice(start, css.indexOf("}", start));
}

describe("command center reading order", () => {
  // Below 640px `.jobs { order: -1 }` once drew the assignments above the
  // team while Tab still visited the team first. The page follows its source
  // order at every width, so no rule may reorder with `order`.
  it("never reorders sections visually away from the keyboard order", () => {
    expect(css).not.toMatch(/(?<![-\w])order\s*:/);
  });
});

describe("command center topbar theming", () => {
  // The topbar once had a hardcoded near-white background overridden only
  // for paper, so Space/Future/Retro kept a near-white header on a dark
  // canvas. The base rule now reads the already-remapped --surface/--line
  // tokens directly, so no per-treatment override is required for those
  // three; paper alone keeps its own bespoke grain background.
  it("uses the themed --surface/--line tokens, not a hardcoded color", () => {
    const body = rule(".topbar");
    expect(body).toMatch(/background:\s*var\(--surface\)/);
    expect(body).toMatch(/border-bottom:\s*1px solid var\(--line\)/);
    expect(body).not.toMatch(/rgba\(/);
  });

  for (const treatment of ["space", "future", "retro"]) {
    it(`${treatment} does not force back the hardcoded near-white topbar`, () => {
      const start = css.indexOf(`.root[data-treatment="${treatment}"] .topbar`);
      expect(start).toBe(-1);
    });
  }
});

describe("command center brand surfaces", () => {
  // .topologyLead::after (the old connector line) is gone; the specialist
  // card took its place as the fourth brand surface checked here.
  for (const selector of [
    ".primary",
    ".primary:hover",
    ".topologyLead",
    ".agent",
  ]) {
    it(`${selector} is a flat brand fill, not a violet gradient`, () => {
      const body = rule(selector);
      expect(body).not.toMatch(/gradient/);
      expect(body).not.toMatch(/#5b3bd8|#4c2fc3|#4d35c6|--violet/i);
    });
  }
});
