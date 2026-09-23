"use client";

import { Pause, Play } from "lucide-react";
import Image from "next/image";
import { type CSSProperties, useEffect, useState } from "react";

import { cn } from "@/lib/utils";

import {
  collageFrame,
  CUT_MS,
  type IntroMotion,
  LANDING_SCRIM_ALPHA,
} from "./intro-motion";

import styles from "./momobot.module.css";

/*
 * Real Momentum scrapbook imagery (provenance: public/momentum/momobot/
 * SOURCES.md), interleaved so a Momo scene, a paper still and an engraving
 * rarely sit next to their own kind.
 */
export const COLLAGE_IMAGES = [
  "/momentum/momobot/collage/scene-wave.webp",
  "/momentum/momobot/collage/still-x2-paper-city.webp",
  "/momentum/momobot/collage/engraving-philly.webp",
  "/momentum/momobot/collage/scene-daily.webp",
  "/momentum/momobot/collage/film-brain.webp",
  "/momentum/momobot/collage/still-x7-bird-plate.webp",
  "/momentum/momobot/collage/scene-idea.webp",
  "/momentum/momobot/collage/still-05-launch-hero.webp",
  "/momentum/momobot/collage/engraving-botanical.webp",
  "/momentum/momobot/collage/scene-pencil.webp",
  "/momentum/momobot/collage/still-x8-scrapbook-opener.webp",
  "/momentum/momobot/collage/film-parts.webp",
  "/momentum/momobot/collage/scene-rocket.webp",
  "/momentum/momobot/collage/still-01-launch-hero.webp",
  "/momentum/momobot/collage/engraving-bird.webp",
  "/momentum/momobot/collage/scene-celebrate.webp",
  "/momentum/momobot/collage/still-x1-momo-machine.webp",
  "/momentum/momobot/collage/film-twine.webp",
  "/momentum/momobot/collage/scene-peek.webp",
  "/momentum/momobot/collage/still-05-launch-burst.webp",
  "/momentum/momobot/collage/still-x3-the-fold.webp",
  "/momentum/momobot/collage/scene-point.webp",
  "/momentum/momobot/collage/still-02-services-detail.webp",
  "/momentum/momobot/collage/film-molecule.webp",
  "/momentum/momobot/collage/scene-thumbs.webp",
  "/momentum/momobot/collage/still-x4-page-writes.webp",
  "/momentum/momobot/collage/still-01-launch-module.webp",
  "/momentum/momobot/collage/scene-sleep.webp",
  "/momentum/momobot/collage/still-x6-particles-cream.webp",
  "/momentum/momobot/collage/still-02-services-hero.webp",
  "/momentum/momobot/collage/still-01-launch-detail.webp",
  "/momentum/momobot/collage/still-03-momo-hero.webp",
  "/momentum/momobot/collage/still-02-services-props.webp",
] as const;

/* Clipping slots: position, width, tilt and crop ratio. Uneven on purpose. */
const SLOTS: { at: CSSProperties; rot: number; ratio: string }[] = [
  {
    at: { top: "4%", left: "3%", width: "clamp(8rem, 17vw, 16rem)" },
    rot: -4,
    ratio: "4 / 3",
  },
  {
    at: { top: "6%", right: "4%", width: "clamp(8rem, 16vw, 15rem)" },
    rot: 5,
    ratio: "1 / 1",
  },
  {
    at: { top: "70%", left: "5%", width: "clamp(8rem, 18vw, 17rem)" },
    rot: -2,
    ratio: "16 / 10",
  },
  {
    at: { top: "72%", right: "6%", width: "clamp(7rem, 15vw, 14rem)" },
    rot: 2.5,
    ratio: "3 / 4",
  },
  {
    at: { top: "37%", left: "-1%", width: "clamp(8rem, 15vw, 14rem)" },
    rot: 3,
    ratio: "3 / 4",
  },
  {
    at: { top: "39%", right: "-1%", width: "clamp(8rem, 17vw, 16rem)" },
    rot: -3,
    ratio: "4 / 3",
  },
  {
    at: { top: "3%", left: "31%", width: "clamp(7rem, 11vw, 11rem)" },
    rot: -6,
    ratio: "1 / 1",
  },
  {
    at: { bottom: "3%", left: "57%", width: "clamp(7rem, 13vw, 12rem)" },
    rot: 4,
    ratio: "4 / 3",
  },
];

/**
 * The newspaper collage behind the cream sign-in sheet and the landing hero.
 * Images load only once the page has settled (after load, at idle), so the
 * form is interactive first. One clipping cuts to a new image every CUT_MS,
 * never faster than once a second, and the cut waits for the next image to
 * decode. Hidden tab, reduced motion or the pause control stop it.
 */
export function ScrapbookBackdrop({
  motion,
  tone,
}: {
  motion: IntroMotion;
  tone: "royal" | "cream";
}) {
  const [ready, setReady] = useState(false);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let idle: number | undefined;
    let timer: number | undefined;
    const go = () => {
      if (typeof window.requestIdleCallback === "function") {
        idle = window.requestIdleCallback(() => setReady(true), {
          timeout: 2000,
        });
      } else {
        timer = window.setTimeout(() => setReady(true), 200);
      }
    };
    if (document.readyState === "complete") go();
    else window.addEventListener("load", go, { once: true });
    return () => {
      window.removeEventListener("load", go);
      if (idle !== undefined) window.cancelIdleCallback(idle);
      window.clearTimeout(timer);
    };
  }, []);

  useEffect(() => {
    if (!ready || !motion.live) return;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      const next = collageFrame(tick + 1, SLOTS.length, COLLAGE_IMAGES.length);
      const img = new window.Image();
      img.src = COLLAGE_IMAGES[next[tick % SLOTS.length]!]!;
      void (img.decode?.() ?? Promise.resolve())
        .catch(() => undefined)
        .then(() => {
          if (!cancelled) setTick((value) => value + 1);
        });
    }, CUT_MS);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [ready, motion.live, tick]);

  const shown = collageFrame(tick, SLOTS.length, COLLAGE_IMAGES.length);

  return (
    <>
      <div
        className={styles.backdrop}
        data-tone={tone}
        data-live={motion.live}
        aria-hidden="true"
      >
        {SLOTS.map((slot, index) => {
          const src = COLLAGE_IMAGES[shown[index]!]!;
          return (
            <div
              key={index}
              className={styles.clipping}
              data-optional={index >= 4}
              style={{ ...slot.at, rotate: `${slot.rot}deg` }}
            >
              <div
                className={cn(
                  styles.clippingPaper,
                  index % 2 === 0 ? "paper-torn" : "paper-torn-alt",
                )}
                style={{ aspectRatio: slot.ratio }}
              >
                {ready && (
                  <Image
                    key={src}
                    className={styles.clippingImage}
                    src={src}
                    alt=""
                    fill
                    sizes="17vw"
                    loading="lazy"
                    unoptimized
                    data-collage-src={src}
                  />
                )}
              </div>
            </div>
          );
        })}
        {/* On cream the doves fly under the scrim, so no dove ever lowers
            hero copy contrast; on royal no copy sits on the backdrop. */}
        {tone === "cream" && motion.motionOk && <PaperDoves />}
        <div
          className={styles.scrim}
          style={{ "--scrim-alpha": LANDING_SCRIM_ALPHA } as CSSProperties}
        />
        {tone === "royal" && motion.motionOk && <PaperDoves />}
      </div>
      {motion.motionOk && (
        <button
          type="button"
          className={styles.motionToggle}
          onClick={() => motion.setPaused(!motion.paused)}
        >
          {motion.paused ? (
            <Play size={14} aria-hidden="true" />
          ) : (
            <Pause size={14} aria-hidden="true" />
          )}
          <span>{motion.paused ? "Play motion" : "Pause motion"}</span>
        </button>
      )}
    </>
  );
}

/*
 * Cut-paper doves, hand-authored: cream body, white wing, a kraft shadow cut
 * a hair lower. Two wing frames stepped by CSS; each dove drifts a long eased
 * path across the backdrop. Reduced motion renders none.
 */
const DOVES = [
  { y: "12%", scale: 1, duration: "46s", delay: "-4s" },
  { y: "30%", scale: 0.7, duration: "58s", delay: "-31s" },
  { y: "58%", scale: 0.85, duration: "52s", delay: "-17s" },
  { y: "80%", scale: 0.6, duration: "64s", delay: "-48s" },
];

const BODY =
  "M9 25C16 19 29 18 41 20C46 15 53 14 57 17L63 19L57 21C54 25 48 28 41 28C31 31 19 31 12 29L2 33L6 27Z";
const WING_UP = "M25 22C27 11 34 4 45 1C41 9 39 15 37 22Z";
const WING_DOWN = "M25 24C28 31 33 37 43 40C40 33 39 28 37 24Z";

function PaperDoves() {
  return (
    <div className={styles.doves}>
      {DOVES.map((dove, index) => (
        <svg
          key={index}
          className={styles.dove}
          viewBox="0 0 64 42"
          style={
            {
              top: dove.y,
              "--dove-scale": dove.scale,
              animationDuration: dove.duration,
              animationDelay: dove.delay,
            } as CSSProperties
          }
        >
          <g transform="translate(1.2 1.8)" fill="#b89a6c" opacity="0.75">
            <path d={BODY} />
            <path className={styles.wingUp} d={WING_UP} />
            <path className={styles.wingDown} d={WING_DOWN} />
          </g>
          <path d={BODY} fill="#f4ecdc" />
          <path className={styles.wingUp} d={WING_UP} fill="#ffffff" />
          <path className={styles.wingDown} d={WING_DOWN} fill="#ffffff" />
          <circle cx="55" cy="18" r="0.9" fill="#101e3f" />
        </svg>
      ))}
    </div>
  );
}
