"use client";

import { Pause, Play } from "lucide-react";
import { type CSSProperties, useEffect, useState } from "react";

import { MomoFilm } from "@/components/momentum/momo-film";

import { type IntroMotion, LANDING_SCRIM_ALPHA } from "./intro-motion";

import styles from "./momobot.module.css";

/**
 * The scrapbook collage behind the cream sign-in sheet and the landing hero:
 * a 6.4s film of hundreds of cutouts (public/momentum/films/SOURCES.md),
 * looped, under the tone scrim. Momo's own films sit in front of it. The film
 * is fetched only once the page has settled (after load, at idle), so the
 * form is interactive first. Hidden tab, reduced motion or the pause control
 * hold its poster, one still collage.
 */
export function ScrapbookBackdrop({
  motion,
  tone,
}: {
  motion: IntroMotion;
  tone: "royal" | "cream";
}) {
  const [ready, setReady] = useState(false);

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

  return (
    <>
      <div
        className={styles.backdrop}
        data-tone={tone}
        data-live={motion.live}
        aria-hidden="true"
      >
        <MomoFilm
          name="momo-collage"
          live={ready && motion.live}
          className={styles.collage}
        />
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
