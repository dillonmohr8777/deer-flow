"use client";

import { Pause, Play } from "lucide-react";
import { type CSSProperties } from "react";

import manifest from "../../../../public/momentum/comic/manifest.json";

import {
  COMIC_BASE,
  COMIC_SCRIM_ALPHA,
  type Manifest,
  rng,
  verb,
} from "./comic-data";

import styles from "./comic.module.css";
import momobot from "./momobot.module.css";

const PANELS = Object.entries(manifest as Manifest)
  .filter(([, m]) => m.kind === "flare")
  .map(([id]) => id);
const COLUMNS = 6;
const PER_COLUMN = 6;

/*
 * Same files as the intro's storm (the browser picks 640w on wide screens,
 * 400w on phones), so after the intro the wall costs no extra bytes.
 */
const SRC_SET = (id: string) =>
  `${COMIC_BASE}/${id}.m.webp 400w, ${COMIC_BASE}/${id}.webp 640w`;
const SIZES = "(max-width: 44rem) 130px, 640px";

// Seeded, so the server and the client draw the same wall.
const WALL = (() => {
  const r = rng(3);
  return Array.from({ length: COLUMNS }, (_, c) =>
    Array.from({ length: PER_COLUMN }, (_, k) => {
      const id = PANELS[(c * 7 + k * 3) % PANELS.length] ?? "";
      return { id, cap: k % 2 ? "" : verb(id), h: 150 + Math.round(r() * 150) };
    }),
  );
})();

/**
 * The settled front door's backdrop: columns of the comic panels drifting
 * slowly behind a cream scrim that keeps the hero copy at contrast. Drift
 * runs only while `live`; reduced motion stills it; Pause motion holds it.
 */
export function ComicWall({
  live,
  motionOk,
  paused,
  showControl,
  onTogglePause,
}: {
  live: boolean;
  motionOk: boolean;
  paused: boolean;
  showControl: boolean;
  onTogglePause: () => void;
}) {
  return (
    <>
      <div
        className={styles.wall}
        data-live={live}
        data-comic-reveal="wall"
        aria-hidden="true"
      >
        <div className={styles.columns}>
          {WALL.map((items, c) => (
            <div
              key={c}
              className={c % 2 ? `${styles.col} ${styles.down}` : styles.col}
              style={{ "--dur": `${110 + c * 23}s` } as CSSProperties}
            >
              {/* Doubled, so a -50% drift loops without a seam. */}
              {[0, 1].map((copy) =>
                items.map((item, k) => (
                  <div
                    key={`${copy}-${k}`}
                    className={styles.wallPanel}
                    style={{ "--h": `${item.h}px` } as CSSProperties}
                  >
                    <img
                      className={styles.photo}
                      alt=""
                      srcSet={SRC_SET(item.id)}
                      sizes={SIZES}
                      src={`${COMIC_BASE}/${item.id}.m.webp`}
                      loading="lazy"
                      decoding="async"
                      fetchPriority="low"
                    />
                    {item.cap ? (
                      <span className={styles.cap} style={{ rotate: "-2deg" }}>
                        {item.cap}
                      </span>
                    ) : null}
                  </div>
                )),
              )}
            </div>
          ))}
        </div>
        <div
          className={styles.scrim}
          style={
            { "--comic-scrim": `${COMIC_SCRIM_ALPHA * 100}%` } as CSSProperties
          }
        />
      </div>
      {motionOk && showControl ? (
        <button
          type="button"
          className={momobot.motionToggle}
          onClick={onTogglePause}
        >
          {paused ? (
            <Play size={14} aria-hidden="true" />
          ) : (
            <Pause size={14} aria-hidden="true" />
          )}
          <span>{paused ? "Play motion" : "Pause motion"}</span>
        </button>
      ) : null}
    </>
  );
}
