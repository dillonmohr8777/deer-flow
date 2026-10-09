import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "@rstest/core";

// Proof for three WCAG AA fixes found in the 2026-09-25 appearance-mode
// evidence run, in the style of tests/unit/paper-tokens.test.ts: every ratio
// is computed from the real stylesheets, resolving each var() to the hex the
// treatment declares, so a later edit to either side of a pair is caught.
//
//   1. Momo Board sent-reply bubble (board.module.css)
//   2. space + retro text on the filled accent (command-center.module.css)
//   3. future sidebar chrome behind nav labels (future.css)

const src = join(__dirname, "..", "..", "src");
const read = (...parts: string[]) => readFileSync(join(src, ...parts), "utf8");

const treatmentCss = {
  paper: read("styles", "paper.css"),
  space: read("styles", "space.css"),
  future: read("styles", "future.css"),
  retro: read("styles", "retro.css"),
} as const;
type Treatment = keyof typeof treatmentCss;
const boardCss = read("components", "workspace", "board", "board.module.css");
const commandCenterCss = read(
  "components",
  "workspace",
  "command-center",
  "command-center.module.css",
);

/** Every `--<treatment>-<name>: #rrggbb;` token across the treatment files. */
const hexTokens: Record<string, string> = {};
for (const css of Object.values(treatmentCss)) {
  const re =
    /--((?:paper|space|future|retro)-[\w-]+):\s*#([0-9a-fA-F]{6})\s*;/g;
  let match: RegExpExecArray | null;
  while ((match = re.exec(css))) {
    const [, name, hex] = match;
    if (name && hex) hexTokens[name] = `#${hex.toLowerCase()}`;
  }
}

/**
 * The declarations of the first rule whose whole selector is `selector`
 * (it must open its line, so `.primary` never matches a treatment-scoped
 * `.root[data-treatment="paper"] .primary`).
 */
function block(css: string, selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = new RegExp(`(?:^|\\n)[ \\t]*${escaped} \\{`).exec(css);
  if (!match) throw new Error(`no rule for ${selector}`);
  const open = match.index + match[0].length;
  return css.slice(open, css.indexOf("}", open));
}

/** The raw value of `--prop` (or `prop`) inside a declaration block. */
function declared(body: string, prop: string): string | undefined {
  const re = new RegExp(`(?:^|[;\\s])${prop}\\s*:\\s*([^;]+);`);
  return re.exec(body)?.[1]?.trim();
}

/** Resolves `#rrggbb` or `var(--token)` to a hex, failing loudly. */
function resolve(value: string | undefined, context: string): string {
  if (!value) throw new Error(`${context}: not declared`);
  const hex = /^#([0-9a-fA-F]{6})$/.exec(value);
  if (hex) return `#${hex[1]!.toLowerCase()}`;
  const ref = /^var\(--([\w-]+)\)$/.exec(value);
  const resolved = ref ? hexTokens[ref[1]!] : undefined;
  if (!resolved) throw new Error(`${context}: cannot resolve ${value}`);
  return resolved;
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
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

/** WCAG contrast ratio between two hex colours, 1..21. */
function contrastRatio(hexA: string, hexB: string): number {
  const lumA = relativeLuminance(hexToRgb(hexA));
  const lumB = relativeLuminance(hexToRgb(hexB));
  const [lighter, darker] = lumA >= lumB ? [lumA, lumB] : [lumB, lumA];
  return (lighter + 0.05) / (darker + 0.05);
}

/** `top` at `alpha` over an opaque `bottom`, as the browser composites it. */
function composite(top: string, alpha: number, bottom: string): string {
  const t = hexToRgb(top);
  const b = hexToRgb(bottom);
  return `#${t
    .map((c, i) => Math.round(alpha * c + (1 - alpha) * b[i]!))
    .map((c) => c.toString(16).padStart(2, "0"))
    .join("")}`;
}

const AA_TEXT = 4.5;
const EPSILON = 0.02;

describe("Momo Board sent-reply bubble (WCAG contrast)", () => {
  const message = block(boardCss, ".message");

  it("fills the bubble with the quiet surface, not the --muted text colour", () => {
    // paper.css binds --muted to ink-muted, a text colour: as a fill it put
    // ink on ink-muted (1.85:1) and the "Owner" label on itself (1:1).
    expect(declared(message, "background")).toBe("var(--muted-surface)");
    expect(message).not.toMatch(/var\(--muted\)/);
    const paperShell = block(
      treatmentCss.paper,
      ':root:not(.dark) [data-workspace-shell][data-treatment="paper"]',
    );
    const inkMuted = resolve(
      declared(paperShell, "--muted-foreground"),
      "paper",
    );
    const ink = resolve(declared(paperShell, "--foreground"), "paper");
    expect(contrastRatio(ink, inkMuted)).toBeLessThan(AA_TEXT);
  });

  // [treatment, measured body ratio, measured author-label ratio]
  const bubbles: Array<[Treatment, number, number]> = [
    ["paper", 12.34, 6.66],
    ["space", 15.27, 10.49],
    ["future", 12.14, 6.39],
    ["retro", 12.94, 8.18],
  ];

  it.each(bubbles)(
    "%s: reply text %f:1 and author label %f:1 on the bubble",
    (treatment, bodyRatio, labelRatio) => {
      const shell = block(
        treatmentCss[treatment],
        `:root:not(.dark) [data-workspace-shell][data-treatment="${treatment}"]`,
      );
      const fill = resolve(declared(shell, "--muted-surface"), treatment);
      const text = resolve(declared(shell, "--foreground"), treatment);
      const label = resolve(declared(shell, "--muted-foreground"), treatment);
      const body = contrastRatio(text, fill);
      const author = contrastRatio(label, fill);
      expect(body).toBeGreaterThanOrEqual(AA_TEXT);
      expect(body).toBeGreaterThanOrEqual(bodyRatio - EPSILON);
      expect(author).toBeGreaterThanOrEqual(AA_TEXT);
      expect(author).toBeGreaterThanOrEqual(labelRatio - EPSILON);
    },
  );
});

describe("Command Center text on the filled accent (WCAG contrast)", () => {
  const base = block(commandCenterCss, ".root");

  function palette(treatment: Treatment | null) {
    const body = treatment
      ? block(commandCenterCss, `.root[data-treatment="${treatment}"]`)
      : base;
    const pick = (prop: string) =>
      resolve(
        declared(body, prop) ?? declared(base, prop),
        `${treatment ?? "current"} ${prop}`,
      );
    return {
      onBlue: pick("--on-blue"),
      blue: pick("--blue"),
      blueDeep: pick("--blue-deep"),
    };
  }

  it("colours the primary action and the lead card with --on-blue, never white", () => {
    for (const selector of [
      ".primary",
      ".topologyLead",
      ".topologyLead div span",
      ".topologyLead a",
    ]) {
      expect(declared(block(commandCenterCss, selector), "color")).toBe(
        "var(--on-blue)",
      );
    }
    expect(commandCenterCss).not.toMatch(/color:\s*white\s*;/);
  });

  it("documents why: white failed on the space and retro accents", () => {
    for (const treatment of ["space", "retro"] as const) {
      const { blue } = palette(treatment);
      expect(contrastRatio("#ffffff", blue)).toBeLessThan(AA_TEXT);
    }
  });

  // [label, on --blue, on --blue-deep, treatment (null = the classic/current base)]
  const fills: Array<[string, number, number, Treatment | null]> = [
    ["classic/current", 6.0, 9.14, null],
    ["paper", 8.24, 12.02, "paper"],
    ["space", 12.86, 12.86, "space"],
    ["future", 6.57, 6.57, "future"],
    ["retro", 8.05, 8.05, "retro"],
  ];

  it.each(fills)(
    "%s: --on-blue reads %f:1 on --blue and %f:1 on --blue-deep",
    (_label, blueRatio, deepRatio, treatment) => {
      const { onBlue, blue, blueDeep } = palette(treatment);
      const onFill = contrastRatio(onBlue, blue);
      const onDeep = contrastRatio(onBlue, blueDeep);
      expect(onFill).toBeGreaterThanOrEqual(AA_TEXT);
      expect(onFill).toBeGreaterThanOrEqual(blueRatio - EPSILON);
      expect(onDeep).toBeGreaterThanOrEqual(AA_TEXT);
      expect(onDeep).toBeGreaterThanOrEqual(deepRatio - EPSILON);
    },
  );
});

describe("future sidebar chrome behind nav labels (WCAG contrast)", () => {
  const sidebar = block(
    treatmentCss.future,
    ':is([data-slot="sidebar-inner"], [data-slot="sidebar"][data-mobile="true"])',
  );

  it("documents why: graphite-lo failed on the bare chrome-deep band", () => {
    expect(
      contrastRatio(
        resolve("var(--future-graphite-lo)", "future"),
        resolve("var(--future-chrome-deep)", "future"),
      ),
    ).toBeLessThan(AA_TEXT);
  });

  it("veils the chrome so its darkest band keeps sidebar text at AA", () => {
    const veil =
      /color-mix\(in srgb, var\(--future-white\) (\d+)%, transparent\)/.exec(
        sidebar,
      );
    expect(veil).not.toBeNull();
    // The veil must sit above the chrome, i.e. be listed first.
    const image = declared(sidebar, "background-image") ?? "";
    expect(image.indexOf("color-mix")).toBeLessThan(
      image.indexOf("var(--future-chrome)"),
    );
    const darkest = composite(
      resolve("var(--future-white)", "future"),
      Number(veil![1]) / 100,
      resolve("var(--future-chrome-deep)", "future"),
    );
    const mutedLabel = contrastRatio(
      resolve("var(--future-graphite-lo)", "future"),
      darkest,
    );
    const label = contrastRatio(
      resolve("var(--future-graphite)", "future"),
      darkest,
    );
    expect(mutedLabel).toBeGreaterThanOrEqual(AA_TEXT);
    expect(mutedLabel).toBeGreaterThanOrEqual(6.52 - EPSILON);
    expect(label).toBeGreaterThanOrEqual(12.38 - EPSILON);
  });
});
