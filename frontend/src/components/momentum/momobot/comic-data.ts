/*
 * The comic intro's score: page layouts, the flip storm, the timeline and the
 * geometry that stamps the wordmark onto the slab. Pure data and functions,
 * so the timing and dealing rules are unit-tested without a browser
 * (tests/unit/components/momentum/comic-data.test.ts). comic-intro.tsx turns
 * this into DOM and Web Animations.
 */

export type ArtMeta = {
  kind: "flare" | "sunburst";
  w: number;
  h: number;
  /** Mean relative luminance, 0..1 (public/momentum/comic/SOURCES.md). */
  lum: number;
};
export type Manifest = Record<string, ArtMeta>;

export const COMIC_BASE = "/momentum/comic";
/** Phones (704 px and under) get the lighter .m variants. */
export const PHONE_MAX_WIDTH = 704;
export const artSrc = (id: string, phone: boolean) =>
  `${COMIC_BASE}/${id}${phone ? ".m" : ""}.webp`;

/** The beats, in ms from the first frame. */
export const T = {
  COLD: 1200, // cold open ends, the storm begins
  STORM_END: 6000, // storm ends on the s03 cut
  TEAM: 7000, // the team lineup, the peak
  S05: 8950, // the slab lands
  STAMP: 9150, // the wordmark stamps onto the slab
  LIFT: 9450, // the block lifts out of the art
  LAND: 10000, // the block lands in the headline
} as const;
/** The hero copy starts arriving here. */
export const SETTLE = T.LIFT + 150;
export const REVEAL_STAGGER = 45;
export const REVEAL_MS = 340;
export const settleEnd = (reveals: number) =>
  SETTLE + 100 + Math.max(0, reveals - 1) * REVEAL_STAGGER + REVEAL_MS;

/** Quad in page units (0..100): TL, TR, BR, BL as x,y pairs. */
export type Quad = readonly [
  number,
  number,
  number,
  number,
  number,
  number,
  number,
  number,
];
export type Layout = "splash" | "split" | "stack3" | "strips" | "tall" | "col";

export const LAYOUT: Record<Layout, readonly Quad[]> = {
  splash: [[2, 3, 98, 3, 98, 97, 2, 97]],
  split: [
    [2, 3, 60, 3, 47, 97, 2, 97],
    [62, 3, 98, 3, 98, 97, 49, 97],
  ],
  stack3: [
    [2, 3, 98, 3, 98, 50, 2, 57],
    [2, 60.5, 55, 56.6, 52, 97, 2, 97],
    [57.5, 56.4, 98, 53.5, 98, 97, 54.5, 97],
  ],
  strips: [
    [2, 3, 34, 3, 29, 97, 2, 97],
    [36, 3, 67, 3, 62, 97, 31, 97],
    [69, 3, 98, 3, 98, 97, 64, 97],
  ],
  tall: [
    [2, 3, 44, 3, 44, 97, 2, 97],
    [47, 3, 98, 3, 98, 46, 47, 52],
    [47, 55, 98, 49, 98, 97, 47, 97],
  ],
  col: [[30, 4, 70, 3, 71, 96, 29, 97]],
};

/** Phones and other tall windows turn every layout on its side. */
export function orient(q: Quad, portrait: boolean): Quad {
  return portrait ? [q[1], q[0], q[7], q[6], q[5], q[4], q[3], q[2]] : q;
}

/**
 * The flip storm, one entry per page: 24 pages. It opens on a mixed layout,
 * the two "!" entries are the orange-hit splash pages, and it ends on a
 * full-bleed finale. Pages name only a layout; dealStorm() picks the art.
 */
export const STORM: readonly string[] = [
  "tall",
  "strips",
  "stack3",
  "strips",
  "split",
  "!t2-builder",
  "tall",
  "strips",
  "split",
  "strips",
  "col",
  "!g01-charge",
  "split",
  "strips",
  "splash",
  "split",
  "splash",
  "split",
  "splash",
  "splash",
  "splash",
  "splash",
  "splash",
  "splash",
];
export const HIT_WORD: Record<string, string> = {
  "t2-builder": "Build",
  "g01-charge": "All in",
};
/** Close-ups: at most one per page, so a page never becomes a wall of faces. */
export const CLOSE: ReadonlySet<string> = new Set([
  "r-analytics-1",
  "r-engineer-2",
  "r-lead-3",
  "r-verifier-1",
  "t1-research",
  "r-reliability-3",
  "r-revenue-3",
  "r-client-success-3",
]);
const VERB: Record<string, string> = {
  analytics: "Measure",
  builder: "Build",
  "client-success": "Deliver",
  engineer: "Ship",
  growth: "Grow",
  lead: "Lead",
  migration: "Move",
  qa: "Check",
  reliability: "Guard",
  research: "Research",
  revenue: "Balance",
  verifier: "Verify",
};
/** The role verb a panel's caption carries ("r-qa-2" -> "Check"), or "". */
export function verb(id: string): string {
  if (id === "t1-research") return "Research";
  if (id === "t2-builder") return "Build";
  if (!id.startsWith("r-")) return "";
  return VERB[id.slice(2, id.lastIndexOf("-"))] ?? "";
}

/** A dealt page: its layout, then one art id per cell ("!" marks a hit). */
export type DealtPage = { layout: Layout; ids: string[] };

/**
 * Deals the art into the storm. Portrait art goes into tall cells and
 * landscape art into wide ones, so no crop turns a panel into a giant face.
 * Art is dealt light to dark by luminance, never two close-ups on a page, and
 * the finale's six splashes run dark to light so the storm climbs into the
 * bright s03 cut. `viewport` is the window: the stack overscans it by 6%.
 */
export function dealStorm(
  manifest: Manifest,
  viewport: { w: number; h: number },
): DealtPage[] {
  const portrait = viewport.h > viewport.w;
  const pool: Record<"P" | "L", string[]> = { P: [], L: [] };
  Object.entries(manifest)
    .filter(([id, m]) => m.kind === "flare" && !HIT_WORD[id])
    .sort((a, b) => b[1].lum - a[1].lum)
    .forEach(([id, m]) => pool[m.h > m.w ? "P" : "L"].push(id));
  const W = viewport.w * 1.06,
    H = viewport.h * 1.06;

  const dealt = STORM.map((spec): DealtPage => {
    if (spec.startsWith("!")) return { layout: "splash", ids: [spec] };
    const layout = spec as Layout;
    let close = false;
    const ids = LAYOUT[layout].map((raw) => {
      const q = orient(raw, portrait);
      const xs = [q[0], q[2], q[4], q[6]],
        ys = [q[1], q[3], q[5], q[7]];
      const aspect =
        ((Math.max(...xs) - Math.min(...xs)) * W) /
        ((Math.max(...ys) - Math.min(...ys)) * H);
      const want = aspect < 1.2 ? "P" : "L";
      const from = pool[want].length
        ? pool[want]
        : pool[want === "P" ? "L" : "P"];
      const k = Math.max(
        0,
        from.findIndex((id) => !close || !CLOSE.has(id)),
      );
      const [id] = from.splice(k, 1);
      if (!id) throw new Error("comic storm ran out of art");
      close ||= CLOSE.has(id);
      return id;
    });
    return { layout, ids };
  });
  const finale = dealt
    .slice(-6)
    .sort((a, b) => lumOf(manifest, a.ids[0]) - lumOf(manifest, b.ids[0]));
  return [...dealt.slice(0, -6), ...finale];
}
const lumOf = (m: Manifest, id: string | undefined) =>
  id ? (m[id]?.lum ?? 0) : 0;

/** Storm holds: linear from ~309 ms to ~91 ms, summing to exactly 4.8 s. */
export function stormHolds(): number[] {
  const raw = STORM.map((_, i) => 90 + 215 * (1 - i / (STORM.length - 1)));
  const norm = (T.STORM_END - T.COLD) / raw.reduce((a, b) => a + b, 0);
  return raw.map((d) => d * norm);
}

export type PagePlan = {
  shown: number;
  exit: number;
  out: "turn" | "cut" | "fade";
  turn: number;
  push?: number;
};

/** Every page, in order: cold open, the 24 storm pages, s03, the team, s05. */
export function planPages(): PagePlan[] {
  const plan: PagePlan[] = [{ shown: 0, exit: T.COLD, out: "turn", turn: 300 }];
  let t = T.COLD;
  for (const hold of stormHolds()) {
    plan.push({
      shown: t,
      exit: t + hold,
      out: "turn",
      turn: Math.max(90, hold * 1.4),
    });
    t += hold;
  }
  plan.push({
    shown: T.STORM_END,
    exit: T.TEAM,
    out: "cut",
    turn: 0,
    push: 1.08,
  });
  plan.push({ shown: T.TEAM, exit: T.S05, out: "cut", turn: 0, push: 1.12 });
  plan.push({ shown: T.S05, exit: T.LIFT, out: "fade", turn: 0 });
  return plan;
}

/** When a page is last drawn: after its turn, at the cut, or after the fade. */
export const pageEnd = (p: PagePlan) =>
  p.out === "turn" ? p.exit + p.turn : p.out === "cut" ? p.exit : T.LIFT + 300;

/**
 * The orange beats: the two storm hit pages (as each is revealed, not when
 * the page above starts turning), the s03 cut, the team and the slab.
 */
export function beats(plan: PagePlan[]): number[] {
  const hits = STORM.flatMap((spec, i) => {
    const page = plan[i + 1],
      above = plan[i];
    return spec.startsWith("!") && page && above
      ? [page.shown + Math.min(160, above.turn * 0.45)]
      : [];
  });
  return [...hits, T.STORM_END, T.TEAM, T.S05];
}

/** Every turn swings the free edge toward the camera. */
export const HINGE = {
  L: { origin: "0% 50%", to: "rotateY(-104deg)", shade: "90deg" },
  R: { origin: "100% 50%", to: "rotateY(104deg)", shade: "270deg" },
  T: { origin: "50% 0%", to: "rotateX(104deg)", shade: "180deg" },
} as const;
export const hingeOf = (i: number) =>
  i % 7 === 3 ? HINGE.R : i % 4 === 2 ? HINGE.T : HINGE.L;

/** The slab face in s05-slab-close, as fractions of the 1536x1024 source. */
export const SLAB_FACE: ReadonlyArray<readonly [number, number]> = [
  [309 / 1536, 190 / 1024],
  [1246 / 1536, 363 / 1024],
  [1345 / 1536, 750 / 1024],
  [364 / 1536, 619 / 1024],
];
/** The wordmark spans this share of the slab face. */
export const STAMP_SHARE = 0.7;

type Pt = readonly [number, number];
/**
 * matrix3d values taking the box (0,0)-(w,h) onto quad p (TL, TR, BR, BL):
 * Heckbert's square-to-quad projective map, scaled to the box.
 */
export function homography(
  w: number,
  h: number,
  [p0, p1, p2, p3]: readonly [Pt, Pt, Pt, Pt],
): number[] {
  const [x0, y0] = p0,
    [x1, y1] = p1,
    [x2, y2] = p2,
    [x3, y3] = p3;
  const dx1 = x1 - x2,
    dx2 = x3 - x2,
    dx3 = x0 - x1 + x2 - x3;
  const dy1 = y1 - y2,
    dy2 = y3 - y2,
    dy3 = y0 - y1 + y2 - y3;
  const den = dx1 * dy2 - dy1 * dx2;
  const g = (dx3 * dy2 - dy3 * dx2) / den,
    k = (dx1 * dy3 - dy1 * dx3) / den;
  const a = x1 - x0 + g * x1,
    b = x3 - x0 + k * x3,
    d = y1 - y0 + g * y1,
    e = y3 - y0 + k * y3;
  return [
    a / w,
    d / w,
    0,
    g / w,
    b / h,
    e / h,
    0,
    k / h,
    0,
    0,
    1,
    0,
    x0,
    y0,
    0,
    1,
  ];
}

/** The quad (viewport px) the wordmark occupies on a slab face given in viewport px. */
export function stampQuad(
  face: readonly [Pt, Pt, Pt, Pt],
  block: { width: number; height: number },
): [Pt, Pt, Pt, Pt] {
  const lerp = (p: Pt, q: Pt, s: number): Pt => [
    p[0] + (q[0] - p[0]) * s,
    p[1] + (q[1] - p[1]) * s,
  ];
  const len = (p: Pt, q: Pt) => Math.hypot(q[0] - p[0], q[1] - p[1]);
  const faceW = (len(face[0], face[1]) + len(face[3], face[2])) / 2;
  const faceH = (len(face[0], face[3]) + len(face[1], face[2])) / 2;
  const fu = STAMP_SHARE,
    fv = Math.min(
      STAMP_SHARE,
      (fu * faceW * block.height) / (block.width * faceH),
    );
  const at = (u: number, v: number) =>
    lerp(lerp(face[0], face[1], u), lerp(face[3], face[2], u), v);
  const u0 = (1 - fu) / 2,
    v0 = (1 - fv) / 2;
  return [at(u0, v0), at(1 - u0, v0), at(1 - u0, 1 - v0), at(u0, 1 - v0)];
}

/**
 * Cream scrim over the settled panel wall, under the whole hero column.
 * Pinned by a contrast test: ink and muted ink stay at 4.5:1 or better over
 * any panel pixel (black, white or royal).
 */
export const COMIC_SCRIM_ALPHA = 0.96;

/** Seeded PRNG (mulberry32): the textures and wall are identical every load, and SSR-safe. */
export function rng(seed: number) {
  let a = seed;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * Whether the intro plays: once per browser session, never under reduced
 * motion, and not on the `?look=current` preview. `?replay` forces it.
 */
export function decideComicIntro(env: {
  reduce: boolean;
  played: boolean;
  search: string;
}): boolean {
  if (env.reduce || /[?&]look=current\b/.test(env.search)) return false;
  return !env.played || /[?&]replay\b/.test(env.search);
}
export const COMIC_SESSION_KEY = "momo-intro";
export const COMIC_ATTR = "data-comic-intro";

/**
 * The same decision as an inline script, run before first paint so the
 * settled hero never flashes before the intro. It only sets
 * html[data-comic-intro="play"]; the landing claims it after hydration.
 */
export const COMIC_BOOT_SCRIPT = `(function(){try{var d=document.documentElement,s=location.search,p=false;try{p=sessionStorage.getItem(${JSON.stringify(COMIC_SESSION_KEY)})==="1"}catch(e){}var r=!!(window.matchMedia&&matchMedia("(prefers-reduced-motion: reduce)").matches);if(!r&&!/[?&]look=current\\b/.test(s)&&(!p||/[?&]replay\\b/.test(s))){d.setAttribute(${JSON.stringify(COMIC_ATTR)},"play");if("scrollRestoration" in history)history.scrollRestoration="manual"}}catch(e){}})();`;
