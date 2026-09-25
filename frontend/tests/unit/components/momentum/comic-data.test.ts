import { runInNewContext } from "node:vm";

import { describe, expect, it } from "@rstest/core";

import {
  beats,
  CLOSE,
  COMIC_ATTR,
  COMIC_BOOT_SCRIPT,
  COMIC_SCRIM_ALPHA,
  COMIC_SESSION_KEY,
  dealStorm,
  decideComicIntro,
  HIT_WORD,
  homography,
  LAYOUT,
  type Manifest,
  orient,
  pageEnd,
  planPages,
  settleEnd,
  STORM,
  stormHolds,
  T,
} from "@/components/momentum/momobot/comic-data";

import manifest from "../../../../public/momentum/comic/manifest.json";

const art = manifest as Manifest;
const DESKTOP = { w: 1280, h: 720 };
const PHONE = { w: 390, h: 844 };

describe("comic intro timeline", () => {
  it("runs the storm from ~309 ms to ~91 ms a page, exactly 4.8 s in all", () => {
    const holds = stormHolds();
    expect(holds).toHaveLength(STORM.length);
    expect(holds.reduce((a, b) => a + b, 0)).toBeCloseTo(
      T.STORM_END - T.COLD,
      6,
    );
    expect(holds[0]).toBeCloseTo(309, 0);
    expect(holds.at(-1)).toBeCloseTo(91, 0);
    holds.slice(1).forEach((h, i) => expect(h).toBeLessThanOrEqual(holds[i]!));
  });

  it("plans every page in order and settles inside 10.5 s", () => {
    const plan = planPages();
    expect(plan).toHaveLength(1 + STORM.length + 3); // cold open, storm, s03, team, s05
    plan
      .slice(1)
      .forEach((p, i) =>
        expect(p.shown).toBeGreaterThanOrEqual(plan[i]!.shown),
      );
    expect(plan.at(-1)).toMatchObject({ shown: T.S05, out: "fade" });
    expect(pageEnd(plan.at(-1)!)).toBe(T.LIFT + 300);
    expect(settleEnd(7)).toBeLessThanOrEqual(10_500);
  });

  it("keeps the orange beats at least a second apart (flash pacing)", () => {
    const hits = beats(planPages());
    expect(hits).toHaveLength(5);
    hits
      .slice(1)
      .forEach((b, i) => expect(b - hits[i]!).toBeGreaterThanOrEqual(1000));
  });
});

describe("dealing the storm", () => {
  for (const [label, view] of [
    ["desktop", DESKTOP],
    ["phone", PHONE],
  ] as const) {
    it(`never repeats a panel and fills every cell (${label})`, () => {
      const pages = dealStorm(art, view);
      const ids = pages.flatMap((p) => p.ids.map((id) => id.replace("!", "")));
      expect(new Set(ids).size).toBe(ids.length);
      pages.forEach((p) =>
        expect(p.ids).toHaveLength(
          p.layout === "splash" && p.ids[0]!.startsWith("!")
            ? 1
            : LAYOUT[p.layout].length,
        ),
      );
      ids.forEach((id) => expect(art[id]).toBeDefined());
    });

    it(`puts at most one close-up on a page (${label})`, () => {
      for (const page of dealStorm(art, view)) {
        expect(
          page.ids.filter((id) => CLOSE.has(id)).length,
        ).toBeLessThanOrEqual(1);
      }
    });
  }

  it("puts portrait art in tall cells on a wide screen", () => {
    const strips = dealStorm(art, DESKTOP).filter((p) => p.layout === "strips");
    expect(strips.length).toBeGreaterThan(0);
    for (const page of strips)
      for (const id of page.ids) expect(art[id]!.h).toBeGreaterThan(art[id]!.w);
  });

  it("lands the two hit pages on their beats and climbs into the light at the end", () => {
    const pages = dealStorm(art, DESKTOP);
    const hits = pages.flatMap((p, i) =>
      p.ids[0]?.startsWith("!") ? [[i, p.ids[0].slice(1)]] : [],
    );
    expect(hits).toEqual([
      [5, "t2-builder"],
      [11, "g01-charge"],
    ]);
    expect(Object.keys(HIT_WORD).sort()).toEqual(["g01-charge", "t2-builder"]);
    const finale = pages.slice(-6).map((p) => art[p.ids[0]!]!.lum);
    expect(finale).toEqual([...finale].sort((a, b) => a - b));
  });

  it("turns layouts on their side in tall windows", () => {
    const q = LAYOUT.tall[0]!;
    expect(orient(q, false)).toBe(q);
    expect(orient(q, true)).toEqual([
      q[1],
      q[0],
      q[7],
      q[6],
      q[5],
      q[4],
      q[3],
      q[2],
    ]);
  });
});

describe("the slab stamp", () => {
  it("maps the block's corners exactly onto the slab quad", () => {
    const w = 600,
      h = 150;
    const quad = [
      [10, 20],
      [520, 80],
      [560, 300],
      [30, 240],
    ] as const;
    const m = homography(w, h, quad);
    const apply = (x: number, y: number) => {
      const X = m[0]! * x + m[4]! * y + m[12]!,
        Y = m[1]! * x + m[5]! * y + m[13]!,
        W = m[3]! * x + m[7]! * y + m[15]!;
      return [X / W, Y / W];
    };
    [
      [0, 0],
      [w, 0],
      [w, h],
      [0, h],
    ].forEach(([x, y], i) => {
      const [px, py] = apply(x!, y!);
      expect(px).toBeCloseTo(quad[i]![0], 6);
      expect(py).toBeCloseTo(quad[i]![1], 6);
    });
  });
});

describe("once per session, never under reduced motion", () => {
  it("decides from motion, session and the URL", () => {
    expect(decideComicIntro({ reduce: false, played: false, search: "" })).toBe(
      true,
    );
    expect(decideComicIntro({ reduce: false, played: true, search: "" })).toBe(
      false,
    );
    expect(
      decideComicIntro({ reduce: false, played: true, search: "?replay" }),
    ).toBe(true);
    expect(
      decideComicIntro({ reduce: true, played: false, search: "?replay" }),
    ).toBe(false);
    expect(
      decideComicIntro({
        reduce: false,
        played: false,
        search: "?look=current",
      }),
    ).toBe(false);
  });

  // The boot script is the same decision, inlined before first paint. Run it
  // in a sandbox whose globals are stubs.
  const boot = (opts: { reduce: boolean; played: boolean; search: string }) => {
    const attrs: Record<string, string> = {};
    const matchMedia = () => ({ matches: opts.reduce });
    const sandbox = {
      document: {
        documentElement: {
          setAttribute: (k: string, v: string) => (attrs[k] = v),
        },
      },
      location: { search: opts.search },
      sessionStorage: {
        getItem: (k: string) =>
          k === COMIC_SESSION_KEY && opts.played ? "1" : null,
      },
      matchMedia,
      history: {},
      window: { matchMedia },
    };
    runInNewContext(COMIC_BOOT_SCRIPT, sandbox);
    return attrs[COMIC_ATTR];
  };

  it("inlines the same decision for first paint", () => {
    for (const reduce of [false, true])
      for (const played of [false, true])
        for (const search of ["", "?replay", "?look=current"]) {
          const expected = decideComicIntro({ reduce, played, search })
            ? "play"
            : undefined;
          expect(boot({ reduce, played, search })).toBe(expected);
        }
  });
});

describe("settled wall scrim", () => {
  const hex = (v: string) =>
    [1, 3, 5].map((i) => parseInt(v.slice(i, i + 2), 16));
  const lum = (rgb: number[]) => {
    const [r, g, b] = rgb.map((v) => {
      const c = v / 255;
      return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * r! + 0.7152 * g! + 0.0722 * b!;
  };
  const contrast = (a: number[], b: number[]) => {
    const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x);
    return (hi! + 0.05) / (lo! + 0.05);
  };

  it("keeps the hero copy at 4.5:1 over any panel pixel", () => {
    const cream = hex("#f2ede3"); // --paper-cream
    for (const ink of ["#101e3f", "#3a4a6b"]) // --paper-ink, --paper-ink-muted
      for (const under of [
        [0, 0, 0],
        [255, 255, 255],
        [27, 75, 158],
        [226, 113, 19],
      ]) {
        const surface = cream.map(
          (c, i) => COMIC_SCRIM_ALPHA * c + (1 - COMIC_SCRIM_ALPHA) * under[i]!,
        );
        expect(contrast(hex(ink), surface)).toBeGreaterThanOrEqual(4.5);
      }
  });
});
