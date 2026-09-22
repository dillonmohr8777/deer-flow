import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "@rstest/core";

/**
 * AVAILABLE_MOMO_SLUGS is a hand-maintained manifest, and the component only
 * reaches for an <img> when a slug is in it. A slug listed without its file
 * fires a real 404 before onError falls back to the glyph, so the two sides
 * have to agree. This is the cheap check that keeps them honest.
 */

const MOMOS_DIR = join(process.cwd(), "public", "momentum", "momos");
const AVATAR_SOURCE = join(
  process.cwd(),
  "src",
  "components",
  "workspace",
  "command-center",
  "momo-avatar.tsx",
);

function manifestSlugs(): string[] {
  const source = readFileSync(AVATAR_SOURCE, "utf8");
  const block = source.match(
    /AVAILABLE_MOMO_SLUGS:\s*ReadonlySet<string>\s*=\s*new Set\(\[([\s\S]*?)\]\)/,
  );
  const body = block?.[1];
  if (!body) throw new Error("could not find AVAILABLE_MOMO_SLUGS in momo-avatar.tsx");
  return [...body.matchAll(/"([^"]+)"/g)].flatMap((match) =>
    match[1] ? [match[1]] : [],
  );
}

function shippedSlugs(): string[] {
  return readdirSync(MOMOS_DIR)
    .filter((name) => name.endsWith(".svg"))
    .map((name) => name.slice(0, -".svg".length))
    .sort();
}

describe("momo manifest", () => {
  it("lists exactly the slugs that have artwork on disk", () => {
    expect([...manifestSlugs()].sort()).toEqual(shippedSlugs());
  });

  it("draws the fallback glyph on the same disc as the shipped artwork", () => {
    // Mapped and unmapped agents sit next to each other in the roster. If these
    // two silhouettes drift apart, the set stops reading as one family.
    const glyphSource = readFileSync(
      join(
        process.cwd(),
        "src",
        "components",
        "workspace",
        "command-center",
        "momentum-glyph.tsx",
      ),
      "utf8",
    );
    const glyphDisc = glyphSource.match(/const DISC =\s*\n?\s*"([^"]+)"/)?.[1];
    const shippedDisc = readFileSync(
      join(MOMOS_DIR, "lead.svg"),
      "utf8",
    ).match(/<path d="(M24\.00[^"]+)" fill/)?.[1];

    expect(glyphDisc).toBeTruthy();
    expect(glyphDisc).toBe(shippedDisc);
  });

  it("ships artwork that is a real single-root svg", () => {
    for (const slug of shippedSlugs()) {
      const svg = readFileSync(join(MOMOS_DIR, `${slug}.svg`), "utf8");
      expect(svg.startsWith("<svg")).toBe(true);
      expect(svg).toContain('viewBox="0 0 48 48"');
      // The detail group is what the <=48px rule hides; without it the brass
      // pin would survive down into the 24px sidebar sizes and turn to mud.
      expect(svg).toContain('class="detail"');
      expect(svg).toContain("@media (max-width: 48px)");
    }
  });
});
