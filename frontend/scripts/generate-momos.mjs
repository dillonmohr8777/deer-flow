/**
 * Generates the shipped Momo avatars in public/momentum/momos/.
 *
 * One shared deckle-edged disc (deterministic jitter, so re-running produces
 * byte-identical files) plus a hand-authored emblem per roster slug. Kept as a
 * generator rather than nine hand-copied files so the disc stays identical
 * across the set: the silhouette is the system, the emblem is the character.
 *
 * Colours come from paper.css. --paper-brass is object-only (2.75 on cream), so
 * it appears here as a pin, never as a glyph carrying meaning.
 *
 * The size rule lives INSIDE each SVG on purpose. momo-avatar.tsx renders these
 * through <img src>, which isolates the SVG from the parent document's CSS, so
 * the module.css `g.detail` rule cannot reach them. An <img>-embedded SVG gets
 * its own viewport equal to the rendered box, so a media query in here does work.
 *
 * Run: node scripts/generate-momos.mjs
 */

import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const OUT_DIR = join(
  dirname(fileURLToPath(import.meta.url)),
  "..",
  "public",
  "momentum",
  "momos",
);

const INK = "#101e3f";
const CREAM = "#fbf8f1";
const BRASS = "#c8a04a";

/** Deterministic hash so the torn edge is stable across runs. */
function jitter(index) {
  const x = Math.sin(index * 12.9898) * 43758.5453;
  return x - Math.floor(x);
}

/** A circle with a torn paper edge: 28 points, radius wobbling 20.4 - 21.8. */
function decklePath() {
  const points = [];
  const count = 28;
  for (let i = 0; i < count; i += 1) {
    const angle = (i / count) * Math.PI * 2 - Math.PI / 2;
    const radius = 20.4 + jitter(i) * 1.4;
    const x = 24 + Math.cos(angle) * radius;
    const y = 24 + Math.sin(angle) * radius;
    points.push(`${x.toFixed(2)} ${y.toFixed(2)}`);
  }
  return `M${points[0]}L${points.slice(1).join("L")}Z`;
}

const DISC = decklePath();

/**
 * Emblems are cream-on-ink, centred on (24,24) and kept inside r=13 so the
 * torn edge never clips them. Stroke-based where possible: a 2.2 stroke still
 * reads at 40px, which is where most of these render.
 */
const STROKE = `fill="none" stroke="${CREAM}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"`;

const MOMOS = {
  // fleet-scout: a magnifier, angled like it is mid-sweep.
  research: `
    <circle cx="22" cy="21.5" r="7.2" ${STROKE} />
    <path d="M27.4 27.2 32.6 32.6" ${STROKE} />`,

  // analytics-engineer: three climbing bars with the trend riding over them.
  analytics: `
    <path d="M17 30.5v-4.6M24 30.5v-9.2M31 30.5v-6.4" ${STROKE} />
    <path d="M15.5 19.5 21 15l4.5 3.6L32.5 13" ${STROKE} />`,

  // data-migration-engineer: here to there. The earlier two-plates-and-an-arc
  // version turned to mush at 24px; two nodes and one arrow survive it.
  migration: `
    <circle cx="14.6" cy="24" r="3.4" fill="${CREAM}" />
    <circle cx="33.4" cy="24" r="3.4" fill="${CREAM}" />
    <path d="M19.6 24h7.2" ${STROKE} />
    <path d="M24.6 21.2 27.4 24l-2.8 2.8" ${STROKE} />`,

  // independent-verifier: a check struck inside a seal.
  verifier: `
    <circle cx="24" cy="24" r="9.4" ${STROKE} />
    <path d="M19.2 24.3 22.8 28 29 19.9" ${STROKE} />`,

  // fleet-builder: a hammer. The triangle-and-crossbar version read as a
  // capital A, which is worse than no mark at all.
  builder: `
    <path d="M15.4 18.4h12.2" fill="none" stroke="${CREAM}" stroke-width="5.6" stroke-linecap="round" />
    <path d="M22.8 22 30.2 32" ${STROKE} />`,

  // fleet-qa: a flask. A bug silhouette needs more pixels than a 24px avatar
  // has, and a magnifier would collide with research.
  qa: `
    <path d="M20.6 14.8v6.6l-5.2 9.4c-.9 1.6.3 3.4 2.1 3.4h13c1.8 0 3-1.8 2.1-3.4l-5.2-9.4v-6.6" ${STROKE} />
    <path d="M18.8 14.8h10.4" ${STROKE} />
    <path d="M17.8 28.2h12.4" ${STROKE} />`,

  // fleet-reliability: a pulse that keeps going.
  reliability: `
    <path d="M12.5 24h5.2l2.6-6.2 3.9 12.6 3-6.4h8.3" ${STROKE} />`,

  // senior-software-engineer: angle brackets, the plainest true thing.
  engineer: `
    <path d="M19.4 17.5 12.8 24l6.6 6.5" ${STROKE} />
    <path d="M28.6 17.5 35.2 24l-6.6 6.5" ${STROKE} />
    <path d="M26.2 15.2 21.8 32.8" ${STROKE} />`,

  // lead: plans and delegates. One centre, work going out to four.
  lead: `
    <circle cx="24" cy="24" r="4.3" ${STROKE} />
    <path d="M24 19.7V14M24 28.3V34M19.7 24H14M28.3 24H34" ${STROKE} />
    <circle cx="24" cy="12.2" r="1.9" fill="${CREAM}" />
    <circle cx="24" cy="35.8" r="1.9" fill="${CREAM}" />
    <circle cx="12.2" cy="24" r="1.9" fill="${CREAM}" />
    <circle cx="35.8" cy="24" r="1.9" fill="${CREAM}" />`,
};

mkdirSync(OUT_DIR, { recursive: true });

for (const [slug, emblem] of Object.entries(MOMOS)) {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" width="48" height="48" role="presentation">
  <style><![CDATA[
    /* An img-embedded SVG gets a viewport equal to its rendered box, so this
       matches the data-size="sm" bucket (48px and under) that module.css
       names. Served as image/svg+xml it is parsed as strict XML, so this stays
       in CDATA and free of raw angle brackets. */
    @media (max-width: 48px) { .detail { display: none; } }
  ]]></style>
  <path d="${DISC}" fill="${INK}" />
  <g>${emblem}
  </g>
  <g class="detail">
    <circle cx="35.6" cy="11.4" r="2.5" fill="${BRASS}" />
    <circle cx="34.9" cy="10.6" r="0.8" fill="${CREAM}" opacity="0.55" />
  </g>
</svg>
`;
  writeFileSync(join(OUT_DIR, `${slug}.svg`), svg, "utf8");
}

console.log(`Wrote ${Object.keys(MOMOS).length} momos to ${OUT_DIR}`);
