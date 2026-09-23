import { readdirSync, readFileSync, statSync } from "node:fs";
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
  const block = /AVAILABLE_MOMO_SLUGS:\s*ReadonlySet<string>\s*=\s*new Set\(\[([\s\S]*?)\]\)/.exec(source);
  const body = block?.[1];
  if (!body) throw new Error("could not find AVAILABLE_MOMO_SLUGS in momo-avatar.tsx");
  return [...body.matchAll(/"([^"]+)"/g)].flatMap((match) =>
    match[1] ? [match[1]] : [],
  );
}

/**
 * The canon Momo palette: paper.css tokens plus the 2026-09-21 re-lock. Kept
 * in step with scripts/generate-momos.mjs, which draws only from this set.
 */
const CANON_PALETTE: ReadonlySet<string> = new Set([
  "#1B4B9E", // royal: the body
  "#14346E", // royal deep: body form, blueprint paper
  "#FFFFFF", // eyes
  "#8E9AA6", // grey hardware and tools
  "#5C6773", // hardware shade
  "#C8A04A", // gold: antenna ball and one rivet only
  "#FBF8F1", // cream-hi: the cut-paper margin
  "#D8C3A0", // kraft: cards, sheets, tags, crates
  "#9A2B3C", // red: the verifier's tag thread
]);

/** The sphere and its crescent, byte for byte in every file. */
const CANON_BODY =
  '<circle cx="60" cy="76" r="48" fill="#1B4B9E"/><path d="M90.81 39.19A48 48 0 1 1 23.19 106.81A48 48 0 0 0 90.81 39.19Z" fill="#14346E"/>';
const CANON_ANTENNA_BALL = '<circle cx="60" cy="11" r="6" fill="#C8A04A"/>';

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

  it("draws every shipped Momo on the one canon body", () => {
    // The crew sits side by side in the roster. The sphere, its crescent and
    // the gold antenna ball are identical in every file; only the tool, pose
    // and eyes change. If the body drifts, the set stops reading as one family.
    for (const slug of shippedSlugs()) {
      const svg = readFileSync(join(MOMOS_DIR, `${slug}.svg`), "utf8");
      expect(svg).toContain(CANON_BODY);
      expect(svg).toContain(CANON_ANTENNA_BALL);
    }
  });

  it("ships artwork that is a real single-root svg", () => {
    for (const slug of shippedSlugs()) {
      const svg = readFileSync(join(MOMOS_DIR, `${slug}.svg`), "utf8");
      expect(svg.startsWith("<svg")).toBe(true);
      expect(svg).toContain('viewBox="0 0 160 160"');
      expect(svg).toMatch(/<title>[^<]+<\/title>/);
      // The detail group is what the <=48px rule hides; without it the fine
      // tool detail would survive down into the 40px roster and turn to mud.
      expect(svg).toContain('class="detail"');
      expect(svg).toContain("@media (max-width: 48px)");
    }
  });

  it("keeps every shipped Momo to the canon palette and under 8 KB", () => {
    for (const slug of shippedSlugs()) {
      const file = join(MOMOS_DIR, `${slug}.svg`);
      const svg = readFileSync(file, "utf8");
      // Every hex, plus every non-hex paint so a named colour cannot slip past.
      const colours = [
        ...svg.matchAll(/#[0-9a-f]{3,8}\b/gi),
        ...svg.matchAll(/(?:fill|stroke)="([^"#]+)"/g),
      ].map(([hex, named]) => (named ?? hex).toUpperCase());
      const offPalette = colours.filter(
        (colour) => colour !== "NONE" && !CANON_PALETTE.has(colour),
      );
      expect({ slug, offPalette }).toEqual({ slug, offPalette: [] });
      // Flat cut paper: no gradients, glows or colour functions.
      expect(svg).not.toMatch(/gradient|<filter|rgba?\(|hsla?\(/i);
      expect(statSync(file).size).toBeLessThan(8 * 1024);
    }
  });
});
