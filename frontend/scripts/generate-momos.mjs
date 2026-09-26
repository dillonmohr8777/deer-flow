/**
 * Generates the shipped Momo avatars in public/momentum/momos/.
 *
 * Every file is the canon Momo, re-locked 2026-09-21: royal sphere body with a
 * deep crescent for form, two white 12x23 pill eyes, grey hardware, gold only
 * on the antenna ball. Geometry is public/momentum/
 * momo-mark.svg and the celebration paper kit (block-shots 2026-09-22), in the
 * same units, placed on a 160 frame. The body is identical across the set; the
 * one grey tool, the pose and the eyes are the character.
 *
 * Cut paper: each piece sits on a cream-hi margin (a 12-unit cream stroke under
 * its silhouette), so a tool laid over the body reads as its own cutout and the
 * whole figure holds up on dark surfaces.
 *
 * The size rule lives INSIDE each SVG on purpose. momo-avatar.tsx renders these
 * through <img src>, which isolates the SVG from the parent document's CSS, so
 * the module.css `g.detail` rule cannot reach them. An <img>-embedded SVG gets
 * its own viewport equal to the rendered box, so a media query in here does
 * work. Everything outside .detail must read at 40px on its own.
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

// The canon palette. tests/unit/components/workspace/momo-manifest.test.ts
// pins every shipped file to exactly this set.
const ROYAL = "#1B4B9E"; // --paper-royal: the body
const DEEP = "#14346E"; // --paper-royal-deep: body form, blueprint paper
const WHITE = "#FFFFFF"; // eyes
const GREY = "#8E9AA6"; // hardware and tools
const SHADE = "#5C6773"; // hardware shade
const GOLD = "#C8A04A"; // --paper-brass: the antenna ball, nothing else
const CREAM = "#FBF8F1"; // --paper-cream-hi: the paper each piece is cut from
const KRAFT = "#D8C3A0"; // --paper-kraft: cards, sheets, tags, crates
const THREAD = "#9A2B3C"; // --paper-danger: the verifier's tag thread, nowhere else

/** The cream paper a piece was cut from, drawn under its silhouette. */
const cut = (shapes) =>
  `<g fill="${CREAM}" stroke="${CREAM}" stroke-width="12" stroke-linejoin="round" stroke-linecap="round">${shapes}</g>`;
/** Fine detail, hidden at 48px and under by the rule every file carries. */
const detail = (shapes) => `<g class="detail">${shapes}</g>`;
const hand = ([x, y]) =>
  `<circle cx="${x}" cy="${y}" r="5.5" fill="${SHADE}"/>`;

/** Arms as [shoulder x, y, hand x, y]; shoulders start under the body. */
const CANON_ARMS = [
  [15, 86, 6, 101],
  [105, 86, 114, 101],
];

/**
 * The deep crescent is the body circle minus the same circle shifted 6 up and
 * 6 left: the paper kit's clip, drawn as one lune so no file needs an id.
 */
const CRESCENT =
  "M90.81 39.19A48 48 0 1 1 23.19 106.81A48 48 0 0 0 90.81 39.19Z";

/** Eye shapes, centred on the canon pills (41, 70.5) and (79, 70.5). */
const EYES = {
  pill: (dx) =>
    `<rect x="${35 + dx}" y="59" width="12" height="23" rx="6"/><rect x="${73 + dx}" y="59" width="12" height="23" rx="6"/>`,
  // Narrowed to read the fine print.
  slit: (dx) =>
    `<rect x="${35 + dx}" y="66.5" width="12" height="8" rx="4"/><rect x="${73 + dx}" y="66.5" width="12" height="8" rx="4"/>`,
  // Level and unimpressed.
  bar: (dx) =>
    `<rect x="${34 + dx}" y="68" width="14" height="5" rx="1"/><rect x="${72 + dx}" y="68" width="14" height="5" rx="1"/>`,
};

function momo({ arms = CANON_ARMS, eyes = "pill", look = 0 }) {
  const armPath = arms
    .map(([x1, y1, x2, y2]) => `M${x1} ${y1}L${x2} ${y2}`)
    .join("");
  const hands = arms.map(([, , x, y]) => [x, y]);
  return (
    cut(
      `<circle cx="60" cy="76" r="48"/><path d="M60 30V11" fill="none"/><circle cx="60" cy="11" r="6"/>` +
        `<path d="${armPath}" fill="none"/>${hands.map(([x, y]) => `<circle cx="${x}" cy="${y}" r="5.5"/>`).join("")}` +
        `<rect x="37" y="112" width="19" height="20" rx="4"/><rect x="64" y="112" width="19" height="20" rx="4"/>`,
    ) +
    `<path d="${armPath}" stroke="${GREY}" stroke-width="7" stroke-linecap="round"/>${hands.map(hand).join("")}` +
    `<path d="M47 112v16M73 112v16" stroke="${GREY}" stroke-width="8"/>` +
    `<path d="M40.5 128.5h12M67.5 128.5h12" stroke="${SHADE}" stroke-width="7" stroke-linecap="round"/>` +
    `<path d="M60 29V14" stroke="${GREY}" stroke-width="7" stroke-linecap="round"/><circle cx="60" cy="11" r="6" fill="${GOLD}"/>` +
    `<circle cx="60" cy="76" r="48" fill="${ROYAL}"/><path d="${CRESCENT}" fill="${DEEP}"/>` +
    detail(`<ellipse cx="60" cy="29.5" rx="7.5" ry="3.2" fill="${SHADE}"/>`) +
    `<g fill="${WHITE}">${EYES[eyes](look)}</g>`
  );
}

// Tool silhouettes reused for their cream margin.
const WRENCH = `<path d="M-3.5 -24.83V-17H3.5V-24.83A9.5 9.5 0 1 1 -3.5 -24.83Z"/><rect x="-4" y="-9" width="8" height="25" rx="4"/>`;
const SHIELD = "M-8 80H28V95C28 108 20 118 10 124C0 118-8 108-8 95Z";
const NEEDLE = "M-3 3A3 3 0 0 1 3 3V34L0 42L-3 34Z";
// A kraft patch torn open at the top of its seam; the rest is stitched.
const TORN_PATCH =
  "M116 100H125L128 105L126.5 107.5L130 112L132.5 106.5L131 104.5L134 100H144V128H116Z";
const RECEIPT =
  "M129 37V26.5L130.67 25L132.33 26.5L134 25L135.67 26.5L137.33 25L139 26.5V37Z";
const PANS = "M98 36H114A8 5 0 0 1 98 36ZM126 36H142A8 5 0 0 1 126 36Z";
const POT = `<rect x="113" y="92" width="28" height="7" rx="2"/><path d="M115.5 99H138.5L135 117H119Z"/>`;
const STEM = "M127 91C125 84 129 76 127 68";
const LEAVES = `<path d="M127 71Q126.2 57.6 113 60Q113.8 73.4 127 71ZM127 69Q142.2 71.2 144 56Q128.8 53.8 127 69Z"/>`;

/**
 * One entry per shipped slug; the slugs and filenames are fixed because
 * momo-avatar.tsx and other surfaces load them by path. `x` places the canon
 * figure in the 160 frame. `back` sits behind the Momo (its hands grip over
 * it), `front` sits over it. Coordinates are canon units.
 */
const MOMOS = {
  // lead: plans and delegates. Pays out rope from a spool; the lines run on
  // out of frame to the rest of the crew.
  lead: {
    title:
      "Momo, lead: holds a spool of rope, its lines running out to the crew",
    x: 6,
    arms: [
      [15, 86, 8, 100],
      [103, 84, 114, 92],
    ],
    back:
      detail(
        `<path d="M134 82L162 42M134 90L162 91M134 98L162 136" stroke="${SHADE}" stroke-width="2.5" stroke-linecap="round"/>`,
      ) +
      cut(`<rect x="113" y="72" width="26" height="36" rx="3"/>`) +
      `<rect x="116" y="78" width="20" height="24" fill="${GREY}"/>` +
      detail(
        `<path d="M116 85l20-3M116 91l20-3M116 97l20-3" stroke="${SHADE}" stroke-width="1.5"/>`,
      ) +
      `<rect x="113" y="72" width="26" height="6" rx="2" fill="${SHADE}"/><rect x="113" y="102" width="26" height="6" rx="2" fill="${SHADE}"/>`,
  },

  // senior-software-engineer: designs before it builds. A blueprint held up,
  // dividers set on it.
  engineer: {
    title:
      "Momo, senior software engineer: holds up a blueprint with dividers set on it",
    x: 4,
    arms: [
      [15, 86, 8, 100],
      [104, 88, 113, 96],
    ],
    back:
      `<g transform="rotate(6 129 81)">` +
      cut(`<rect x="113" y="60" width="32" height="42" rx="1.5"/>`) +
      `<rect x="113" y="60" width="32" height="42" rx="1.5" fill="${DEEP}"/>` +
      detail(
        `<path d="M121 60v42M129 60v42M137 60v42M113 70h32M113 80h32M113 90h32" stroke="${ROYAL}" stroke-width="1"/>`,
      ) +
      `<path d="M129 66L119 98M129 66L139 98" stroke="${GREY}" stroke-width="5.5" stroke-linecap="round"/>` +
      `<circle cx="129" cy="66" r="5.5" fill="${GREY}"/>` +
      detail(`<circle cx="129" cy="66" r="2" fill="${SHADE}"/>`) +
      `</g>`,
  },

  // data-migration-engineer: moves the load and can move it back. Wrench up,
  // the crate on casters rolled against its side.
  migration: {
    title:
      "Momo, data migration engineer: wrench raised, a crate on casters at its side",
    x: 15,
    arms: [
      [18, 82, 6, 66],
      [102, 92, 110, 99],
    ],
    back:
      cut(
        `<rect x="104" y="98" width="34" height="26" rx="1.5"/><circle cx="112" cy="129" r="4"/><circle cx="130" cy="129" r="4"/>`,
      ) +
      detail(
        `<path d="M112 124v4M130 124v4" stroke="${GREY}" stroke-width="3"/>`,
      ) +
      `<circle cx="112" cy="129" r="4" fill="${SHADE}"/><circle cx="130" cy="129" r="4" fill="${SHADE}"/>` +
      `<rect x="104" y="98" width="34" height="26" rx="1.5" fill="${KRAFT}"/>` +
      detail(
        `<path d="M104 106.5h34M104 115.5h34M108.5 98v26M133.5 98v26" stroke="${SHADE}" stroke-width="1.5"/>`,
      ) +
      `<g transform="translate(4 58) rotate(-14)">${cut(WRENCH)}<g fill="${GREY}">${WRENCH}</g></g>`,
  },

  // independent-verifier: trusts nothing it has not read. Turned left, eyes
  // narrowed, magnifier over a separate sheet; a kraft tag on red thread.
  // Shares the facing-left pose with qa; the two differ by pose and eyes.
  verifier: {
    title:
      "Momo, independent verifier: faces left with narrowed eyes, magnifier over a separate sheet, kraft tag on red thread",
    x: 37,
    tilt: -5,
    eyes: "slit",
    look: -9,
    arms: [
      [17, 90, 7, 95],
      [104, 90, 110, 104],
    ],
    back:
      cut(`<rect x="-30" y="98" width="36" height="30" rx="1"/>`) +
      `<rect x="-30" y="98" width="36" height="30" rx="1" fill="${KRAFT}"/>` +
      detail(
        `<path d="M-25 105h22M-25 111h26M-25 117h16M-25 123h24" stroke="${SHADE}" stroke-width="2" stroke-linecap="round"/>`,
      ),
    // The lens stays open (a cream ring, not a disc) so the sheet shows through.
    front:
      `<g fill="none" stroke="${CREAM}" stroke-linecap="round"><circle cx="-12" cy="110" r="12.5" stroke-width="11"/><path d="M-3 103L6 96" stroke-width="18"/></g>` +
      detail(
        `<path d="M-17 110h9" stroke="${SHADE}" stroke-width="4" stroke-linecap="round"/>`,
      ) +
      `<path d="M-3 103L6 96" stroke="${SHADE}" stroke-width="6" stroke-linecap="round"/>` +
      `<circle cx="-12" cy="110" r="9.5" fill="none" stroke="${GREY}" stroke-width="5"/>` +
      hand([7, 95]) +
      detail(
        `<path d="M63 22C70 22 73 28 72 35" fill="none" stroke="${THREAD}" stroke-width="1.6" stroke-linecap="round"/>` +
          `<g transform="rotate(12 76 41)"><path d="M69 35h14v12H69l-3-3v-6z" fill="${KRAFT}"/><circle cx="70" cy="41" r="1.4" fill="${SHADE}"/></g>`,
      ),
  },

  // analytics-engineer: reconciles before it reports. A slide rule held like a
  // staff and a bar chart card held up.
  analytics: {
    title:
      "Momo, analytics engineer: slide rule in one hand, a bar chart card in the other",
    x: 16,
    arms: [
      [15, 88, 2, 100],
      [104, 90, 111, 99],
    ],
    back:
      cut(`<rect x="-6" y="54" width="12" height="74" rx="2"/>`) +
      `<rect x="-6" y="54" width="12" height="74" rx="2" fill="${GREY}"/>` +
      detail(
        `<path d="M-2 54v74M2 54v74" stroke="${SHADE}" stroke-width="1"/>` +
          `<path d="M-6 60h3M-6 66h2M-6 72h3M-6 90h3M-6 96h2M-6 108h3M-6 114h2M-6 120h3M3 63h3M4 69h2M3 93h3M4 111h2M3 117h3" stroke="${SHADE}" stroke-width="1"/>`,
      ) +
      `<rect x="-7.5" y="76" width="15" height="7" rx="1.5" fill="${SHADE}"/>`,
    front:
      `<g transform="rotate(5 122 83)">` +
      cut(`<rect x="107" y="64" width="30" height="38" rx="1.5"/>`) +
      `<rect x="107" y="64" width="30" height="38" rx="1.5" fill="${KRAFT}"/>` +
      `<path d="M114.5 96V86M122 96V78M129.5 96V71" stroke="${ROYAL}" stroke-width="6"/>` +
      detail(`<path d="M110 96.5h24" stroke="${SHADE}" stroke-width="1.5"/>`) +
      `</g>` +
      hand([111, 99]),
  },

  // fleet-scout: maps the ground before anyone moves. An index card held up,
  // clipped.
  research: {
    title: "Momo, fleet scout: holds up an index card with a paperclip",
    x: 8,
    arms: [
      [15, 86, 6, 101],
      [103, 84, 112, 87],
    ],
    front:
      `<g transform="rotate(-8 126 80)">` +
      cut(
        `<rect x="107" y="67" width="38" height="26" rx="1.5"/><path d="M118 72V62a2.5 2.5 0 0 1 5 0v16a4 4 0 0 1-8 0V59" fill="none"/>`,
      ) +
      `<rect x="107" y="67" width="38" height="26" rx="1.5" fill="${KRAFT}"/>` +
      detail(
        `<path d="M111 73.5h30" stroke="${ROYAL}" stroke-width="1.2"/><path d="M111 79.5h30M111 85.5h30" stroke="${SHADE}" stroke-width="1"/>`,
      ) +
      `<path d="M118 72V62a2.5 2.5 0 0 1 5 0v16a4 4 0 0 1-8 0V59" fill="none" stroke="${GREY}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>` +
      `</g>` +
      hand([112, 87]),
  },

  // fleet-builder: assembles the thing. Hammer up.
  builder: {
    title: "Momo, fleet builder: hammer raised",
    x: 8,
    arms: [
      [15, 86, 6, 101],
      [100, 78, 112, 64],
    ],
    back:
      `<g transform="translate(112 64) rotate(14)">` +
      cut(
        `<rect x="-3.5" y="-36" width="7" height="50" rx="3"/><rect x="-16" y="-47" width="33" height="14" rx="2.5"/>`,
      ) +
      `<rect x="-3.5" y="-36" width="7" height="50" rx="3" fill="${SHADE}"/>` +
      `<rect x="-16" y="-46" width="28" height="12" rx="2" fill="${GREY}"/><rect x="10" y="-47" width="7" height="14" rx="2" fill="${SHADE}"/>` +
      detail(
        `<path d="M-16 -40h5" stroke="${CREAM}" stroke-width="2"/><circle cx="0" cy="-40" r="2" fill="${SHADE}"/>`,
      ) +
      `</g>`,
  },

  // fleet-reliability: guards scope with rollback evidence. A shield up.
  reliability: {
    title: "Momo, fleet reliability: guards with a shield",
    x: 24,
    arms: [
      [18, 92, 10, 101],
      [105, 86, 114, 101],
    ],
    front:
      cut(`<path d="${SHIELD}"/>`) +
      `<path d="${SHIELD}" fill="${GREY}" stroke="${SHADE}" stroke-width="3" stroke-linejoin="round"/>` +
      detail(
        `<path d="M10 83V120" stroke="${SHADE}" stroke-width="3"/><circle cx="10" cy="97" r="3.2" fill="${SHADE}"/>`,
      ),
  },

  // fleet-qa: validates without editing. Turned left, flat eyes, the rubber
  // stamp raised and held, not yet pressed.
  qa: {
    title:
      "Momo, fleet QA: faces left with flat eyes, rubber stamp raised, not pressed",
    x: 26,
    eyes: "bar",
    look: -9,
    arms: [
      [20, 62, 3, 47],
      [105, 86, 114, 101],
    ],
    // Lifted by the knob and hanging pad-down beside the head: raised, not
    // pressed. The arm reaches the knob above the block, so nothing crosses it.
    front:
      `<g transform="translate(0 44) rotate(6)">` +
      cut(
        `<circle r="7.5"/><rect x="-3.5" y="6" width="7" height="10"/><rect x="-14" y="15" width="28" height="21.5" rx="2"/>`,
      ) +
      `<rect x="-3.5" y="6" width="7" height="10" fill="${GREY}"/>` +
      `<rect x="-9" y="15" width="18" height="5" rx="1.5" fill="${SHADE}"/><rect x="-14" y="20" width="28" height="12" rx="2" fill="${GREY}"/>` +
      detail(`<rect x="-14" y="28" width="28" height="4" fill="${SHADE}"/>`) +
      `<rect x="-13" y="32" width="26" height="4.5" rx="1" fill="${ROYAL}"/><circle r="7.5" fill="${GREY}"/>` +
      `</g>` +
      hand([3, 47]),
  },

  // client-success: keeps the relationship whole. A stitch just pulled
  // through: needle up, point leading, the thread running on from its eye to
  // the newest stitch under what is left of a small torn seam.
  "client-success": {
    title:
      "Momo, client success: mends a small torn seam with needle and thread",
    x: 8,
    arms: [
      [15, 86, 6, 101],
      [104, 84, 122.5, 78],
    ],
    back:
      cut(`<path d="${TORN_PATCH}"/>`) +
      `<path d="${TORN_PATCH}" fill="${KRAFT}"/>` +
      detail(
        `<path d="M130 112l-1.5 3.5 2.5 3-2 3.5 1.5 3-.5 3" fill="none" stroke="${SHADE}" stroke-width="1.2" stroke-linejoin="round"/>`,
      ) +
      `<path d="M126 113.5l8 3M126 118.5l8 3M126 123.5l8 3" stroke="${ROYAL}" stroke-width="2.6" stroke-linecap="round"/>`,
    // Eye end down by the patch, point up; the eye clears the hand.
    front:
      `<g transform="translate(114 96) rotate(-155)">` +
      cut(`<path d="${NEEDLE}"/>`) +
      `<path d="${NEEDLE}" fill="${GREY}"/><rect x="-1.2" y="3.5" width="2.4" height="7.5" rx="1.2" fill="${SHADE}"/>` +
      `</g>` +
      detail(
        `<path d="M117.1 89.4C119 100 121 109 126 113.5" fill="none" stroke="${ROYAL}" stroke-width="1.8" stroke-linecap="round"/>`,
      ) +
      hand([122.5, 78]),
  },

  // revenue: reconciles what was billed with what was paid. A balance scale
  // held up and level: a coin in one pan, a receipt in the other.
  revenue: {
    title:
      "Momo, revenue: holds up a level balance scale, a coin in one pan and a receipt in the other",
    x: 8,
    arms: [
      [15, 86, 6, 101],
      [103, 70, 117, 58],
    ],
    front:
      cut(
        `<rect x="118" y="14" width="4" height="53" rx="2"/><circle cx="120" cy="13" r="3.5"/>` +
          `<rect x="104" y="16.5" width="32" height="4.5" rx="2.25"/><circle cx="106" cy="31.5" r="5.5"/><path d="${RECEIPT}${PANS}"/>`,
      ) +
      `<path d="M106 19L98.5 36M106 19L113.5 36M134 19L126.5 36M134 19L141.5 36" stroke="${SHADE}" stroke-width="1.8" stroke-linecap="round"/>` +
      `<rect x="118" y="14" width="4" height="53" rx="2" fill="${GREY}"/>` +
      `<circle cx="120" cy="13" r="3.5" fill="${SHADE}"/>` +
      `<rect x="104" y="16.5" width="32" height="4.5" rx="2.25" fill="${GREY}"/>` +
      detail(`<circle cx="120" cy="18.75" r="1.6" fill="${SHADE}"/>`) +
      // The coin is grey on purpose: gold stays on the antenna.
      `<circle cx="106" cy="31.5" r="5.5" fill="${GREY}"/>` +
      `<path d="${RECEIPT}" fill="${KRAFT}"/>` +
      detail(
        `<circle cx="106" cy="31.5" r="3.3" fill="none" stroke="${SHADE}" stroke-width="1.2"/><path d="M131 29.5h6M131 32h4" stroke="${SHADE}" stroke-width="1"/>`,
      ) +
      `<path d="${PANS}" fill="${SHADE}"/>` +
      hand([117, 58]),
  },

  // growth: grows the account steadily, not in spikes. A seedling in a small
  // grey pot, held out on one hand.
  growth: {
    title: "Momo, growth: holds out a seedling in a small pot",
    x: 6,
    arms: [
      [15, 86, 8, 100],
      [104, 90, 114, 106],
    ],
    front:
      cut(`${POT}<path d="${STEM}" fill="none"/>${LEAVES}`) +
      `<path d="${STEM}" fill="none" stroke="${ROYAL}" stroke-width="3.5" stroke-linecap="round"/>` +
      `<g fill="${ROYAL}">${LEAVES}</g>` +
      detail(
        `<path d="M127 71L116.5 63M127 69L139 60.5" stroke="${DEEP}" stroke-width="1.2" stroke-linecap="round"/><ellipse cx="127" cy="92" rx="11" ry="2.5" fill="${SHADE}"/>`,
      ) +
      `<g fill="${GREY}">${POT}</g>` +
      detail(`<path d="M115.5 99h23" stroke="${SHADE}" stroke-width="1.5"/>`) +
      hand([114, 106]),
  },
};

mkdirSync(OUT_DIR, { recursive: true });

for (const [slug, role] of Object.entries(MOMOS)) {
  const place = `translate(${role.x} 12)${role.tilt ? ` rotate(${role.tilt} 60 130)` : ""}`;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 160" width="160" height="160" role="img">
<title>${role.title}</title>
<style><![CDATA[
  /* An img-embedded SVG gets a viewport equal to its rendered box, so this
     matches the data-size="sm" bucket (48px and under) that module.css
     names. Served as image/svg+xml it is parsed as strict XML, so this stays
     in CDATA and free of raw angle brackets. */
  @media (max-width: 48px) { .detail { display: none; } }
]]></style>
<g transform="${place}">${role.back ?? ""}${momo(role)}${role.front ?? ""}</g>
</svg>
`;
  writeFileSync(join(OUT_DIR, `${slug}.svg`), svg, "utf8");
}

console.log(`Wrote ${Object.keys(MOMOS).length} momos to ${OUT_DIR}`);
