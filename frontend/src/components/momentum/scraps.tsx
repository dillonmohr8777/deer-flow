"use client";

/*
 * Permanent scrapbook decoration: torn-paper cutouts from
 * public/momentum/scraps/*.webp (see that folder's SOURCES.md), each with a
 * washi-tape strip and a slow sway. Purely decorative, so the container is
 * aria-hidden and every image carries an empty alt; callers place the
 * cluster with their own className. [data-live="false"] pauses the sway
 * (matches momobot.module.css's paper doves); reduced motion removes the
 * sway too but keeps the paper in place. Hidden under the future and retro
 * treatments, which do not want torn paper.
 */

import type { CSSProperties } from "react";

import { cn } from "@/lib/utils";

import styles from "./scraps.module.css";

export const SCRAP_NAMES = [
  "blue-circle",
  "blue-scrap",
  "blue-strip",
  "blue-yellow",
  "brushes",
  "call",
  "circles",
  "coast",
  "coast-road",
  "compass",
  "cyclist",
  "exclamation",
  "handoff",
  "handshake",
  "headphones",
  "laptop",
  "leaf-shadow",
  "night-office",
  "old-town",
  "phone",
  "santorini",
  "seedling",
  "sky",
  "skyline-meeting",
  "speech-bubbles",
  "storefront",
  "sunflowers",
  "tablet",
  "train",
  "twine",
  "vase",
  "writing",
  "yellow-scrap",
] as const;

export type ScrapName = (typeof SCRAP_NAMES)[number];

/** Base tilt by index, degrees. Cycles for a longer cluster. */
const TILTS = [-6, 4, -2, 5, -4];
/** Sway duration by index, seconds (7 to 9), cycling alongside the tilts. */
const DURATIONS = [7, 7.5, 8, 8.5, 9];
/** Stagger step for the negative animation delay, seconds. */
const DELAY_STEP = 1.1;

export function Scraps({
  names,
  live,
  size = 64,
  className,
}: {
  names: readonly ScrapName[];
  live: boolean;
  size?: number;
  className?: string;
}) {
  return (
    <div
      className={cn(styles.scraps, className)}
      aria-hidden="true"
      data-live={live}
    >
      {names.map((name, index) => (
        <span
          key={name}
          className={styles.scrap}
          style={
            {
              "--scrap-tilt": `${TILTS[index % TILTS.length]}deg`,
              animationDuration: `${DURATIONS[index % DURATIONS.length]}s`,
              animationDelay: `${-(index * DELAY_STEP)}s`,
            } as CSSProperties
          }
        >
          <img
            src={`/momentum/scraps/${name}.webp`}
            alt=""
            loading="lazy"
            decoding="async"
            width={size}
          />
        </span>
      ))}
    </div>
  );
}
