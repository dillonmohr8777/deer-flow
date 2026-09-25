"use client";

import {
  type CSSProperties,
  type RefObject,
  useEffect,
  useMemo,
  useRef,
} from "react";

import manifest from "../../../../public/momentum/comic/manifest.json";

import {
  artSrc,
  beats,
  COMIC_ATTR,
  COMIC_RUNNING_ATTR,
  COMIC_SESSION_KEY,
  dealStorm,
  decideComicIntro,
  type DealtPage,
  EARLY_PAGES,
  GATE_HOLD_MS,
  hingeOf,
  HIT_WORD,
  homography,
  LAYOUT,
  LOAD_DEADLINE_MS,
  type Manifest,
  NON_SKIP_KEYS,
  orient,
  pageEnd,
  PHONE_MAX_WIDTH,
  planPages,
  REVEAL_MS,
  REVEAL_STAGGER,
  rng,
  SETTLE,
  SLAB_FACE,
  stampQuad,
  T,
  verb,
} from "./comic-data";

import styles from "./comic.module.css";

/*
 * The front door's ten-second comic intro (DESIGN.md motion item 7, approved
 * by Dillon 2026-09-24). A cold-open panel, a 17-page flip storm under a
 * rising blue wash, the team splashes, then the slab lands and the real
 * MomoBotBlock is stamped onto it in perspective and flown into the headline.
 * It plays once per session; Skip intro, any click or any key (except Tab and
 * modifiers alone) skips it; reduced motion never sees it: the landing claims
 * it with claimComicIntro().
 */

const ART = manifest as Manifest;

/**
 * Claims the intro for this page view. True when it should play. Idempotent,
 * because React strict mode mounts twice: the answer lives on
 * html[data-comic-intro] ("play" or "done"), which COMIC_BOOT_SCRIPT may
 * already have set before first paint.
 */
export function claimComicIntro(): boolean {
  const html = document.documentElement;
  let state = html.getAttribute(COMIC_ATTR);
  if (state !== "play" && state !== "done") {
    let played = false;
    try {
      played = sessionStorage.getItem(COMIC_SESSION_KEY) === "1";
    } catch {
      // Storage can be blocked; the intro then plays, and stays skippable.
    }
    const reduce =
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    state = decideComicIntro({ reduce, played, search: window.location.search })
      ? "play"
      : "done";
    html.setAttribute(COMIC_ATTR, state);
  }
  if (state === "play") {
    try {
      sessionStorage.setItem(COMIC_SESSION_KEY, "1");
    } catch {
      // See above.
    }
  }
  return state === "play";
}

/** Ends the intro's hold on the page: the settled hero shows. */
export function releaseComicIntro() {
  document.documentElement.setAttribute(COMIC_ATTR, "done");
}

const f1 = (n: number) => n.toFixed(1);
const svgUrl = (s: string) =>
  `url("data:image/svg+xml,${encodeURIComponent(s)}")`;

/** The wash's halftone edge, as a mask: dots swell row by row into solid. */
function band() {
  let c = "";
  for (let j = 0; j < 15; j++) {
    const rad = 0.6 + Math.pow(j / 14, 1.3) * 10.2;
    for (let i = 0; i < 76; i++)
      c += `<circle cx='${i * 16 + (j % 2) * 8}' cy='${j * 16 + 8}' r='${f1(rad)}'/>`;
  }
  return svgUrl(
    `<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1216 240'><g>${c}</g></svg>`,
  );
}

/** An uneven 16-spike starburst for the beat captions. */
function star() {
  const r = rng(5),
    pts: string[] = [];
  for (let k = 0; k < 32; k++) {
    const rad = k % 2 ? 0.34 + r() * 0.04 : 0.46 + r() * 0.05,
      a = (k / 32) * 2 * Math.PI;
    pts.push(
      `${f1(50 + rad * 100 * Math.cos(a))}% ${f1(50 + rad * 100 * Math.sin(a))}%`,
    );
  }
  return `polygon(${pts.join(",")})`;
}

/**
 * An image that loads now (`eager`) or when the loading queue reaches it
 * (data-src): the first storm pages get the bandwidth before the rest.
 */
function Art({
  src,
  eager,
  className,
  high,
  slab,
}: {
  src: string;
  eager: boolean;
  className?: string;
  high?: boolean;
  slab?: boolean;
}) {
  return (
    <img
      className={className}
      alt=""
      src={eager ? src : undefined}
      data-src={eager ? undefined : src}
      data-comic-slab={slab ? "" : undefined}
      fetchPriority={high ? "high" : undefined}
    />
  );
}

function StormPage({
  page,
  index,
  phone,
  portrait,
}: {
  page: DealtPage;
  index: number;
  phone: boolean;
  portrait: boolean;
}) {
  const polys = LAYOUT[page.layout].map((q) => orient(q, portrait));
  const fullBleed = page.layout === "splash";
  return (
    <>
      {page.ids.map((raw, k) => {
        const q = polys[k];
        if (!q) return null;
        const id = raw.replace("!", "");
        const xs = [q[0], q[2], q[4], q[6]],
          ys = [q[1], q[3], q[5], q[7]];
        const x0 = Math.min(...xs),
          x1 = Math.max(...xs),
          y0 = Math.min(...ys),
          y1 = Math.max(...ys);
        const clip = xs
          .map(
            (x, n) =>
              `${f1(((x - x0) / (x1 - x0)) * 100)}% ${f1((((ys[n] ?? 0) - y0) / (y1 - y0)) * 100)}%`,
          )
          .join(",");
        return (
          <div
            key={k}
            className={styles.cell}
            style={{
              left: `${x0}%`,
              top: `${y0}%`,
              width: `${x1 - x0}%`,
              height: `${y1 - y0}%`,
              clipPath: `polygon(${clip})`,
            }}
          >
            <Art
              className={styles.photo}
              src={artSrc(id, phone, fullBleed, ART[id])}
              eager={index < EARLY_PAGES}
              high={index < 2}
            />
          </div>
        );
      })}
      <svg
        className={styles.frames}
        viewBox="0 0 100 100"
        preserveAspectRatio="none"
        aria-hidden="true"
      >
        {polys.slice(0, page.ids.length).map((q, k) => (
          <polygon
            key={k}
            points={[0, 2, 4, 6].map((n) => `${q[n]},${q[n + 1]}`).join(" ")}
          />
        ))}
      </svg>
      {page.ids.map((raw, k) => {
        const q = polys[k];
        const id = raw.replace("!", ""),
          hit = raw.startsWith("!");
        const word = hit ? HIT_WORD[id] : k === 0 && index < 13 ? verb(id) : "";
        if (!q || !word) return null;
        // Captions sit well inside the page, where the camera push never crops them.
        const pos: CSSProperties =
          hit || (index + k) % 2 === 0
            ? {
                left: `${f1(Math.max(q[0], q[6]) + (hit ? 11 : 7))}%`,
                top: `${f1(Math.max(q[1], q[3]) + (hit ? 13 : 9))}%`,
              }
            : {
                right: `${f1(100 - Math.min(q[2], q[4]) + 7)}%`,
                bottom: `${f1(100 - Math.min(q[5], q[7]) + 9)}%`,
              };
        const tilt = hit ? -6 : (index + k) % 3 === 0 ? 2 : -2;
        return (
          <span
            key={`c${k}`}
            className={hit ? `${styles.cap} ${styles.burst}` : styles.cap}
            style={{ ...pos, rotate: `${tilt}deg` }}
          >
            {word}
          </span>
        );
      })}
    </>
  );
}

function Framed({
  id,
  phone,
  eager = false,
  slab,
}: {
  id: string;
  phone: boolean;
  eager?: boolean;
  slab?: boolean;
}) {
  return (
    <>
      <div className={styles.dots} data-comic-dots="" />
      <div className={styles.frame} data-comic-frame="">
        <Art src={artSrc(id, phone)} eager={eager} high={eager} slab={slab} />
      </div>
    </>
  );
}

export function ComicIntro({
  root,
  onDone,
}: {
  root: RefObject<HTMLElement | null>;
  onDone: () => void;
}) {
  // Client-only: the landing mounts this after claimComicIntro() says play.
  const view = useMemo(
    () => ({ w: window.innerWidth, h: window.innerHeight }),
    [],
  );
  const phone = view.w <= PHONE_MAX_WIDTH,
    portrait = view.h > view.w;
  const dealt = useMemo(() => dealStorm(ART, view), [view]);
  const textures = useMemo(
    () => ({ "--comic-band": band(), "--comic-star": star() }) as CSSProperties,
    [],
  );
  const stackRef = useRef<HTMLDivElement>(null);
  const overlayRef = useRef<HTMLDivElement>(null);
  const hitRef = useRef<HTMLDivElement>(null);
  const skipRef = useRef<HTMLButtonElement>(null);

  const pages = useMemo(
    () => [
      {
        cls: styles.page,
        body: <Framed id="s01-coldopen" phone={phone} eager />,
      },
      ...dealt.map((page, i) => ({
        cls: styles.page,
        body: (
          <StormPage page={page} index={i} phone={phone} portrait={portrait} />
        ),
      })),
      {
        cls: `${styles.page} ${styles.splash}`,
        body: <Framed id="s03-charge" phone={phone} />,
      },
      {
        // Tall screens: the peak fills the screen and the camera pans the lineup.
        cls: `${styles.page} ${styles.splash}${portrait ? ` ${styles.fill}` : ""}`,
        body: <Framed id="t3-team" phone={phone} />,
      },
      {
        cls: `${styles.page} ${styles.splash}`,
        body: <Framed id="s05-slab-close" phone={phone} slab />,
      },
    ],
    [dealt, phone, portrait],
  );

  useEffect(() => {
    const stack = stackRef.current,
      overlay = overlayRef.current,
      hit = hitRef.current,
      skipBtn = skipRef.current,
      host = root.current;
    const block = host?.querySelector<HTMLElement>("[data-comic-block]");
    if (
      !stack ||
      !overlay ||
      !hit ||
      !skipBtn ||
      !host ||
      !block ||
      typeof overlay.animate !== "function"
    ) {
      releaseComicIntro(); // no Web Animations: straight to the settled page
      onDone();
      return;
    }
    const part = (name: string) =>
      block.querySelector<HTMLElement>(`[data-comic-part="${name}"]`);
    const pageEls = [...stack.children] as HTMLElement[];
    const plan = planPages();
    const A: Animation[] = []; // the timeline: paused by the loading gates, awaited to finish
    const loose: Animation[] = []; // ambience that keeps moving through a loading hold
    const timers: number[] = [];
    let over = false;

    // Nothing behind the intro takes focus: Skip intro is the first stop.
    const behind = [
      ...host.querySelectorAll<HTMLElement>("[data-comic-reveal]"),
    ].filter((el) => el.getAttribute("data-comic-reveal") !== "wall");
    behind.forEach((el) => (el.inert = true));
    const restore = () => behind.forEach((el) => (el.inert = false));

    const go = (el: Element, kf: Keyframe[], o: KeyframeAnimationOptions) => {
      const a = el.animate(kf, { fill: "both", ...o });
      A.push(a);
      return a;
    };
    /** keys: [ms, props, easing?] -> keyframes with offsets over the last key's time. */
    const track = (el: Element, keys: Array<[number, Keyframe, string?]>) => {
      const end = keys[keys.length - 1]?.[0] ?? 1;
      return go(
        el,
        keys.map(([k, p, e]) => ({
          ...p,
          offset: k / end,
          ...(e ? { easing: e } : {}),
        })),
        { duration: end },
      );
    };
    const detach = () => {
      removeEventListener("pointerdown", skip);
      removeEventListener("keydown", onKey);
      skipBtn.removeEventListener("click", skip);
    };
    const finish = () => {
      if (over) return;
      over = true;
      detach();
      timers.forEach((t) => clearTimeout(t));
      const hadFocus = document.activeElement === skipBtn;
      releaseComicIntro(); // show the page first, then drop the animations: no hidden frame between
      document.documentElement.removeAttribute(COMIC_RUNNING_ATTR);
      restore();
      [...A, ...loose].forEach((a) => a.cancel());
      block.style.transformOrigin = "";
      if (hadFocus) host.querySelector<HTMLElement>("a[href]")?.focus();
      onDone();
    };
    function skip() {
      A.forEach((a) => {
        try {
          a.finish();
        } catch {
          // An animation with no end (none in A) cannot finish; cancel covers it.
        }
      });
      finish();
    }
    function onKey(e: KeyboardEvent) {
      if (!NON_SKIP_KEYS.has(e.key)) skip();
    }

    const play = () => {
      if (over) return;
      // The boot script already released a page that waited too long.
      if (document.documentElement.getAttribute(COMIC_ATTR) !== "play")
        return finish();
      document.documentElement.setAttribute(COMIC_RUNNING_ATTR, "");
      pageEls.forEach((page, i) => {
        const P = plan[i];
        if (!P) return;
        const end = pageEnd(P);
        const on: Array<[number, Keyframe]> =
          P.shown === 0
            ? [[0, { opacity: 1 }]]
            : [
                [0, { opacity: 0 }],
                [P.shown, { opacity: 0 }],
                [P.shown, { opacity: 1 }],
              ];
        const off: Array<[number, Keyframe]> =
          P.out === "fade"
            ? [
                [T.LIFT, { opacity: 1 }],
                [end, { opacity: 0 }],
              ]
            : [
                [end, { opacity: 1 }],
                [end, { opacity: 0 }],
              ];
        track(page, [...on, ...off]);
        // Cull: a page is painted only from 0.7 s before it shows until it is gone.
        const from = Math.max(0, P.shown - 700);
        track(page, [
          [0, { visibility: "hidden" }],
          [from, { visibility: "hidden" }],
          [from, { visibility: "visible" }],
          [end, { visibility: "visible" }],
          [end, { visibility: "hidden" }],
        ]);
        const hinge = hingeOf(i);
        page.style.transformOrigin = hinge.origin;
        if (P.out === "turn")
          go(page, [{ transform: "none" }, { transform: hinge.to }], {
            delay: P.exit,
            duration: P.turn,
            easing: "cubic-bezier(.45,0,.9,.5)",
          });
        const art = page.querySelector<HTMLElement>("[data-comic-frame] img");
        if (art && page.classList.contains(styles.fill ?? "")) {
          // Tall screens: pan the whole lineup, left to right.
          const box = page.getBoundingClientRect();
          const span = box.height * 1.5 - box.width;
          go(
            art,
            [
              { transform: `translateX(${f1(-0.08 * span)}px)` },
              { transform: `translateX(${f1(-0.92 * span)}px)` },
            ],
            {
              delay: P.shown,
              duration: P.exit - P.shown,
              easing: "cubic-bezier(.45,0,.55,1)",
            },
          );
        } else if (P.push && art)
          go(art, [{ transform: "none" }, { transform: `scale(${P.push})` }], {
            delay: P.shown,
            duration: P.exit - P.shown,
            easing: "cubic-bezier(.3,0,.6,1)",
          });
      });

      // Cold open: the panel drifts onto the page, then keeps pushing in while
      // the halftone drifts, even through a loading hold.
      const cold = pageEls[0];
      const coldFrame = cold?.querySelector("[data-comic-frame]"),
        coldArt = cold?.querySelector("[data-comic-frame] img"),
        coldDots = cold?.querySelector("[data-comic-dots]");
      if (coldFrame)
        go(
          coldFrame,
          [
            { transform: "translateY(9%) rotate(-3deg) scale(.88)" },
            { transform: "translateY(0) rotate(-.4deg) scale(1.05)" },
          ],
          { duration: T.COLD, easing: "cubic-bezier(.15,.6,.3,1)" },
        );
      if (coldArt)
        loose.push(
          coldArt.animate(
            [{ transform: "none" }, { transform: "scale(1.4)" }],
            {
              duration: 9000,
              easing: "linear",
              fill: "both",
            },
          ),
        );
      if (coldDots) {
        loose.push(
          coldDots.animate(
            [
              { transform: "translate(0, 0)" },
              { transform: "translate(-14px, -14px)" },
            ],
            { duration: 1400, iterations: Infinity, easing: "linear" },
          ),
        );
        loose.push(
          coldDots.animate([{ opacity: 0.05 }, { opacity: 0.15 }], {
            duration: 700,
            direction: "alternate",
            iterations: Infinity,
            easing: "ease-in-out",
          }),
        );
      }

      // Camera: a linear push through the storm, then a shake as the slab lands.
      const camera = overlay.querySelector("[data-comic-camera]");
      if (camera)
        track(camera, [
          [0, { transform: "none" }],
          [T.COLD, { transform: "scale(1) rotate(-.6deg)" }, "linear"],
          [T.STORM_END, { transform: "scale(1.25) rotate(.6deg)" }],
          [T.STORM_END, { transform: "none" }],
          [T.S05, { transform: "none" }],
          [T.S05, { transform: "translate(0,0) scale(1.07)" }],
          [T.S05 + 40, { transform: "translate(-14px,8px) scale(1.06)" }],
          [T.S05 + 80, { transform: "translate(11px,-6px) scale(1.04)" }],
          [T.S05 + 120, { transform: "translate(-6px,3px) scale(1.02)" }],
          [T.S05 + 170, { transform: "none" }],
          [T.LAND, { transform: "none" }],
        ]);

      // The blue wash rises through the storm and lifts off the finale, which
      // climbs dark to light into ALL IN and the charge.
      const washKeys = (o: number): Array<[number, Keyframe, string?]> => [
        [0, { transform: "translateY(130%)", opacity: o }],
        [
          3600,
          { transform: "translateY(130%)", opacity: o },
          "cubic-bezier(.35,0,.75,.7)",
        ],
        [
          T.STORM_END - 350,
          { transform: "translateY(0%)", opacity: o },
          "ease-in",
        ],
        [T.STORM_END, { transform: "translateY(0%)", opacity: 0 }],
        [T.LAND, { transform: "translateY(0%)", opacity: 0 }],
      ];
      overlay
        .querySelectorAll("[data-comic-wash]")
        .forEach((w) =>
          track(
            w,
            washKeys(w.getAttribute("data-comic-wash") === "deep" ? 0.25 : 0.8),
          ),
        );

      // Orange beats: two clean tapered streaks sweep across, eased.
      beats(plan).forEach((at) => {
        go(
          hit,
          [
            { opacity: 0 },
            { opacity: 1, offset: 0.15 },
            { opacity: 1, offset: 0.7 },
            { opacity: 0 },
          ],
          { delay: at, duration: 420, fill: "none" },
        );
        hit.querySelectorAll("[data-comic-streak]").forEach((s) =>
          go(
            s,
            [
              { transform: "translateX(-110vw)" },
              { transform: "translateX(110vw)" },
            ],
            {
              delay: at,
              duration: 420,
              easing: "cubic-bezier(.65,0,.35,1)",
              fill: "none",
            },
          ),
        );
      });

      // The stamp: the hero block itself, projected onto the slab face (source
      // art is 3:2, fitted with object-fit: cover).
      const r = block.getBoundingClientRect();
      const slabImg = overlay.querySelector("[data-comic-slab]");
      if (slabImg) {
        const box = slabImg.getBoundingClientRect(),
          s = Math.max(box.width / 1536, box.height / 1024);
        const onArt = ([u, v]: readonly [number, number]): readonly [
          number,
          number,
        ] => [
          box.left + (box.width - 1536 * s) / 2 + u * 1536 * s - r.left,
          box.top + (box.height - 1024 * s) / 2 + v * 1024 * s - r.top,
        ];
        const face = SLAB_FACE.map(onArt) as unknown as Parameters<
          typeof stampQuad
        >[0];
        const H = `matrix3d(${homography(r.width, r.height, stampQuad(face, r))
          .map((n) => +n.toFixed(6))
          .join(",")})`;
        block.style.transformOrigin = "0 0";
        go(block, [{ opacity: 0 }, { opacity: 1 }], {
          delay: T.STAMP,
          duration: 1,
        });
        go(block, [{ transform: H }, { transform: H }], { duration: T.LIFT });
        go(block, [{ transform: H }, { transform: "none" }], {
          delay: T.LIFT,
          duration: T.LAND - T.LIFT,
          easing: "cubic-bezier(.5,0,.2,1)",
          fill: "forwards",
        });
      } else {
        go(block, [{ opacity: 0 }, { opacity: 1 }], {
          delay: T.LIFT,
          duration: 300,
        });
      }
      const word = part("word"),
        plate = part("plate"),
        stripe = part("stripe"),
        antenna = part("antenna");
      if (word)
        go(
          word,
          [
            { opacity: 0, transform: "scale(1.6)" },
            { opacity: 1, transform: "none" },
          ],
          {
            delay: T.STAMP,
            duration: 200,
            easing: "cubic-bezier(.2,.9,.3,1.25)",
          },
        );
      // The slab is the plate until lift-off.
      if (plate) {
        go(
          plate,
          [{ opacity: 0 }, { opacity: 0, offset: 0.999 }, { opacity: 1 }],
          { duration: T.LIFT },
        );
        go(plate, [{ opacity: 0 }, { opacity: 1 }], {
          delay: T.LIFT,
          duration: 240,
          fill: "forwards",
        });
      }
      if (stripe)
        go(stripe, [{ transform: "scaleX(0)" }, { transform: "none" }], {
          delay: T.LAND - 260,
          duration: 220,
          easing: "cubic-bezier(.7,0,.2,1)",
        });
      if (antenna)
        go(
          antenna,
          [
            { transform: "scaleY(0)" },
            { transform: "scaleY(1.25)", offset: 0.6 },
            { transform: "none" },
          ],
          { delay: T.LAND - 140, duration: 300, easing: "ease-out" },
        );

      // Settle: the wall fades up and the page arrives around the block.
      let k = 0;
      host
        .querySelectorAll<HTMLElement>("[data-comic-reveal]")
        .forEach((el) => {
          if (el.getAttribute("data-comic-reveal") === "wall") {
            go(el, [{ opacity: 0 }, { opacity: 1 }], {
              delay: SETTLE,
              duration: 600,
            });
          } else {
            go(
              el,
              [
                { opacity: 0, translate: "0 12px" },
                { opacity: 1, translate: "0 0" },
              ],
              {
                delay: SETTLE + 100 + k++ * REVEAL_STAGGER,
                duration: REVEAL_MS,
                easing: "cubic-bezier(.2,.8,.2,1)",
              },
            );
          }
        });

      // Loading, in timeline order: the first storm pages load first; the rest
      // load four at a time in page order once those are in, so the next page
      // is always first in line. Each later page has a gate. A gate holds (the
      // cold open keeps moving) until LOAD_DEADLINE_MS after navigation, and
      // later ones at most GATE_HOLD_MS; then the settled page shows.
      const imgsOf = (from: number, to: number) =>
        pageEls.slice(from, to).flatMap((p) => [...p.querySelectorAll("img")]);
      const early = imgsOf(1, EARLY_PAGES + 1);
      const queue = imgsOf(EARLY_PAGES + 1, pageEls.length).filter(
        (im) => im.dataset.src,
      );
      let active = 0;
      const pump = () => {
        while (!over && active < 4 && queue.length) {
          const im = queue.shift();
          if (!im) break;
          const next = () => {
            active--;
            pump();
          };
          active++;
          im.addEventListener("load", next, { once: true });
          im.addEventListener("error", next, { once: true });
          im.src = im.dataset.src ?? "";
        }
      };
      void Promise.all(
        early.map((im) => im.decode().catch(() => undefined)),
      ).then(pump);
      const ready = (im: HTMLImageElement) =>
        im.complete && im.naturalWidth > 0;
      const gate = (atMs: number, imgs: HTMLImageElement[]) => {
        const g = host.animate([], { duration: atMs });
        A.push(g);
        g.finished.then(
          () => {
            if (over || imgs.every(ready)) return;
            A.forEach((a) => {
              if (a !== g && a.playState === "running") a.pause();
            });
            const budget = Math.max(
              GATE_HOLD_MS,
              LOAD_DEADLINE_MS - performance.now(),
            );
            const late = new Promise<"late">((res) =>
              timers.push(window.setTimeout(() => res("late"), budget)),
            );
            void Promise.race([
              Promise.all(
                imgs.map(
                  (im) =>
                    im.src
                      ? im.decode().catch(() => undefined)
                      : Promise.resolve(), // not queued yet: checked by ready() below
                ),
              ).then(() => "ok" as const),
              late,
            ]).then((s) => {
              if (over) return;
              if (s === "late" || !imgs.every(ready)) skip();
              else
                A.forEach((a) => {
                  if (a.playState === "paused") a.play();
                });
            });
          },
          () => undefined,
        );
      };
      gate(T.COLD - 200, early);
      for (let i = EARLY_PAGES + 1; i < pageEls.length; i++) {
        const P = plan[i],
          page = pageEls[i];
        if (P && page) gate(P.shown - 120, [...page.querySelectorAll("img")]);
      }

      Promise.all(A.map((a) => a.finished)).then(finish, () => undefined);
    };

    // Skip intro, any click, or any key but Tab and modifiers: from the first frame.
    skipBtn.addEventListener("click", skip);
    addEventListener("pointerdown", skip);
    addEventListener("keydown", onKey);

    // First beat: the cold-open art and the display face, by LOAD_DEADLINE_MS
    // after navigation, or the settled page instead of a stall.
    const coldImg = pageEls[0]?.querySelector("img");
    const firstBeat = Promise.all([
      coldImg?.decode(),
      document.fonts?.load('400 1em "Archivo Black"'),
    ]);
    const late = new Promise<"late">((res) =>
      timers.push(
        window.setTimeout(
          () => res("late"),
          Math.max(0, LOAD_DEADLINE_MS - performance.now()),
        ),
      ),
    );
    void Promise.race([firstBeat.then(() => "ok" as const), late]).then(
      (s) => {
        if (s !== "ok") return finish();
        try {
          play();
        } catch {
          finish(); // a broken timeline never strands the page or its inert links
        }
      },
      () => finish(),
    );

    return () => {
      over = true;
      document.documentElement.removeAttribute(COMIC_RUNNING_ATTR);
      detach();
      timers.forEach((t) => clearTimeout(t));
      restore();
      [...A, ...loose].forEach((a) => a.cancel());
      block.style.transformOrigin = "";
    };
  }, [root, onDone, dealt.length]);

  return (
    <>
      <div
        ref={overlayRef}
        className={styles.intro}
        style={textures}
        aria-hidden="true"
      >
        <div className={styles.camera} data-comic-camera="">
          <div ref={stackRef} className={styles.stack} data-comic-stack="">
            {pages.map((p, i) => (
              <div key={i} className={p.cls} style={{ zIndex: 100 - i }}>
                {p.body}
              </div>
            ))}
          </div>
          <div className={styles.wash} data-comic-wash="color">
            <div className={styles.band} />
          </div>
          <div
            className={`${styles.wash} ${styles.deep}`}
            data-comic-wash="deep"
          >
            <div className={styles.band} />
          </div>
        </div>
      </div>
      <div ref={hitRef} className={styles.hit} aria-hidden="true">
        <div
          className={`${styles.streak} ${styles.bold}`}
          data-comic-streak=""
        />
        <div
          className={`${styles.streak} ${styles.fine}`}
          data-comic-streak=""
        />
      </div>
      <button ref={skipRef} type="button" className={styles.skip}>
        Skip intro
      </button>
    </>
  );
}
