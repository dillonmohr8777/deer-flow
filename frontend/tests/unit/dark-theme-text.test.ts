import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "@rstest/core";

// Guards for the 2026-10-20 "no dark on dark" fixes. The live audit found navy
// paper ink and faded placeholders on the dark canvas; these keep the fixes in
// place: text on the workspace follows the theme tokens, and the dark token
// pairs clear WCAG AA.

const src = join(__dirname, "..", "..", "src");
const read = (...p: string[]) => readFileSync(join(src, ...p), "utf8");

/** oklch(L C H) to a linear-light sRGB luminance, enough for a contrast check. */
function oklchLuminance(l: number, c: number, h: number): number {
  const a = c * Math.cos((h * Math.PI) / 180);
  const b = c * Math.sin((h * Math.PI) / 180);
  const l_ = (l + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m_ = (l - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s_ = (l - 0.0894841775 * a - 1.291485548 * b) ** 3;
  const lin = [
    4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_,
    -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_,
    -0.0041960863 * l_ - 0.7034186147 * m_ + 1.707614701 * s_,
  ].map((v) => Math.min(1, Math.max(0, v)));
  return 0.2126 * lin[0]! + 0.7152 * lin[1]! + 0.0722 * lin[2]!;
}

const ratio = (a: number, b: number) =>
  (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);

function darkToken(name: string): number {
  const css = read("styles", "globals.css");
  const dark = css.slice(css.indexOf("\n.dark {"));
  const m = new RegExp(
    `--${name}:\\s*oklch\\(([\\d.]+) ([\\d.]+) ([\\d.]+)\\)`,
  ).exec(dark);
  if (!m) throw new Error(`--${name} not found in .dark`);
  return oklchLuminance(+m[1]!, +m[2]!, +m[3]!);
}

describe("dark theme text tokens", () => {
  it.each([
    ["foreground", "background"],
    ["muted-foreground", "background"],
    ["muted-foreground", "muted-surface"],
    ["muted-foreground", "card"],
  ])("--%s on --%s is at least 4.5:1", (fg, bg) => {
    expect(ratio(darkToken(fg), darkToken(bg))).toBeGreaterThanOrEqual(4.5);
  });
});

describe("workspace text follows the theme", () => {
  it("the lineup and About page do not hard-code navy paper ink for text", () => {
    const css = read("components", "workspace", "lineup", "lineup.module.css");
    expect(css).not.toMatch(/(^|[^-])color:\s*var\(--paper-ink/m);
  });

  it("placeholders use the muted token at full opacity", () => {
    expect(read("styles", "globals.css")).toMatch(
      /::placeholder\s*\{\s*color:\s*var\(--muted-foreground\);\s*opacity:\s*1;/,
    );
    expect(read("components", "ui", "textarea.tsx")).not.toContain(
      "placeholder:text-muted-foreground/60",
    );
  });

  it("inactive paper tabs use the theme muted token, not navy ink-muted", () => {
    const css = read("styles", "paper.css");
    const rule =
      /\[data-treatment="paper"\] \[data-slot="tabs-trigger"\]:not\(\[data-state="active"\]\) \{([^}]*)\}/.exec(
        css,
      );
    expect(rule?.[1]).toContain("var(--muted-foreground)");
  });

  it("the cream sign-in sheet pins its foreground tokens to ink", () => {
    const css = read("app", "invite", "invite.module.css");
    const sheet = /\n\.sheet \{([^}]*)\}/.exec(css)?.[1] ?? "";
    expect(sheet).toContain("--foreground: var(--paper-ink)");
    expect(sheet).toContain("--muted-foreground: var(--paper-ink-muted)");
  });
});

describe("paper fonts follow no theme", () => {
  // Oct 22: dark paper fell back to the system face while light used Nunito.
  it("sets the body and dialog-title fonts outside any light-only scope", () => {
    const paper = read("styles", "paper.css");
    const rules = [...paper.matchAll(/([^{}]+)\{([^{}]*)\}/g)];
    const owns = (decl: RegExp) =>
      rules.filter(
        ([, sel, body]) => decl.test(body!) && sel!.includes("paper"),
      );
    for (const decl of [
      /font-family:\s*var\(--m-font-text\)/,
      /font-family:\s*var\(--m-font-serif\)/,
    ]) {
      const found = owns(decl);
      expect(found.length).toBeGreaterThan(0);
      for (const [, sel] of found) {
        expect(sel).not.toMatch(/not\(\.dark\)/);
      }
    }
  });
});
