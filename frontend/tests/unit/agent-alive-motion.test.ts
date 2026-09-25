import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "@rstest/core";

// DESIGN.md Motion item 7 (agents alive). Reads the real stylesheets, so the
// gate is proven in CSS, not only by the component's data-live switch.
const styles = join(__dirname, "..", "..", "src");
const paperCss = readFileSync(join(styles, "styles", "paper.css"), "utf8");
const aliveCss = readFileSync(
  join(
    styles,
    "components",
    "workspace",
    "command-center",
    "agent-alive.module.css",
  ),
  "utf8",
);

/** The body of the first `@media (prefers-reduced-motion: no-preference)`
 *  block that mentions `.paper-alive`. */
function aliveMotionBlock(css: string): string {
  const marker = "@media (prefers-reduced-motion: no-preference)";
  let from = 0;
  for (;;) {
    const start = css.indexOf(marker, from);
    if (start < 0) throw new Error("no gated block animates .paper-alive");
    let depth = 0;
    let end = start;
    for (let i = css.indexOf("{", start); i < css.length; i++) {
      if (css[i] === "{") depth++;
      if (css[i] === "}" && --depth === 0) {
        end = i;
        break;
      }
    }
    const block = css.slice(start, end + 1);
    if (block.includes(".paper-alive")) return block;
    from = end;
  }
}

describe("agents alive motion", () => {
  it("animates only inside the reduced-motion AND brand-motion gate", () => {
    const block = aliveMotionBlock(paperCss);
    const rules = block.match(/[^{}]+\{\s*animation:[^}]+\}/g) ?? [];
    expect(rules).toHaveLength(3);
    for (const rule of rules) {
      expect(rule).toContain('[data-treatment="paper"][data-motion="on"]');
      expect(rule).toContain('[data-live="true"]');
    }
    // Idle and failed never move.
    expect(block).not.toMatch(/data-alive="(idle|failed)"/);
    // No other rule anywhere animates the avatar.
    const outside = paperCss.replace(block, "");
    expect(outside).not.toMatch(/\.paper-alive[^{]*\{[^}]*animation/);
    expect(aliveCss).not.toMatch(/animation|transition/);
  });

  it("moves transform and opacity only", () => {
    const keyframes =
      paperCss.match(
        /@keyframes paper-alive-[\w-]+\s*\{(?:[^{}]*\{[^}]*\})+\s*\}/g,
      ) ?? [];
    expect(keyframes).toHaveLength(3);
    for (const frames of keyframes) {
      const properties = [...frames.matchAll(/([\w-]+)\s*:/g)].map((m) => m[1]);
      for (const property of properties)
        expect(["transform", "opacity"]).toContain(property);
    }
  });
});
