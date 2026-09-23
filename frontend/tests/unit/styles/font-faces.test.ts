import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "@rstest/core";

/**
 * fonts.css declared Fraunces, Caveat and Playfair Display for a day without
 * any of their files being committed. @font-face fails silently: the browser
 * just falls back, so the serif and script voices were quietly rendering as
 * system faces on every surface and nothing caught it. This is the check that
 * would have.
 */

const FONTS_CSS = join(process.cwd(), "src", "styles", "fonts.css");

describe("font faces", () => {
  it("only declares faces whose files are actually shipped", () => {
    const css = readFileSync(FONTS_CSS, "utf8");
    const urls = [...css.matchAll(/url\("([^"]+)"\)/g)].map(
      (match) => match[1]!,
    );

    expect(urls.length).toBeGreaterThan(0);

    const missing = urls.filter(
      (url) => !existsSync(join(process.cwd(), "public", url)),
    );
    expect(missing).toEqual([]);
  });

  it("keeps a font-family declared for every voice variable it defines", () => {
    const css = readFileSync(FONTS_CSS, "utf8");
    const families = new Set(
      [...css.matchAll(/@font-face\s*{[^}]*?font-family:\s*"([^"]+)"/gs)].map(
        (match) => match[1]!,
      ),
    );

    // Every --m-font-* variable's first (preferred) family must either be a
    // declared @font-face or a generic/system keyword. A variable pointing at
    // a named face with no @font-face is the same silent fallback bug.
    const variables = [...css.matchAll(/--m-font-[a-z-]+:\s*([^;]+);/g)].map(
      (match) => match[1]!.trim(),
    );
    expect(variables.length).toBeGreaterThan(0);

    for (const value of variables) {
      const first = value.split(",")[0]!.trim();
      if (!first.startsWith('"')) continue; // system keyword like ui-monospace
      const family = first.replaceAll('"', "");
      expect(
        families.has(family),
        `--m-font-* prefers "${family}" but no @font-face declares it`,
      ).toBe(true);
    }
  });
});
