"use client";

import { useEffect, useState } from "react";

import { brandMotionAllowed } from "@/components/workspace/command-center/appearance-preferences";

/*
 * Motion contract for the MomoBot front door (landing and sign in).
 *
 * Signed-out pages sit outside the workspace appearance provider, so they ask
 * brandMotionAllowed() with what they can know: the OS motion preference and
 * tab visibility, plus the visitor's own pause control. Server render and
 * first paint are motion-off, so nothing moves before hydration.
 */

/** The collage never cuts faster than once a second (no flashing). */
export const MIN_CUT_MS = 1000;
export const CUT_MS = Math.max(MIN_CUT_MS, 1100);

/**
 * Cream scrim over the collage under the landing hero copy. Pinned by a
 * contrast test: ink and muted ink stay at 4.5:1 or better over any image.
 */
export const LANDING_SCRIM_ALPHA = 0.86;

/** Stepped wave: 0,1,0,2,0,3 at about 160ms a frame, a pause, once more. */
export const WAVE_FRAME_MS = 160;
export const WAVE_PAUSE_MS = 480;
export const WAVE_SEQUENCE = [0, 1, 0, 2, 0, 3] as const;
/** Sprite frame 4 is frame 0 with the eyelids closed. */
export const BLINK_FRAME = 4;
export const BLINK_MS = 140;

export type WaveStep = { frame: number; ms: number };

export function waveTimeline(): WaveStep[] {
  const once = WAVE_SEQUENCE.map((frame) => ({ frame, ms: WAVE_FRAME_MS }));
  return [
    ...once,
    { frame: 0, ms: WAVE_PAUSE_MS },
    ...once,
    { frame: 0, ms: 0 },
  ];
}

/**
 * Which image each clipping slot shows after `tick` cuts. One slot changes
 * per cut, round robin, and the images walk forward through the list so no
 * image repeats on screen while there are more images than slots.
 */
export function collageFrame(tick: number, slots: number, images: number) {
  return Array.from({ length: slots }, (_, slot) => {
    const cutsHere =
      tick > slot ? Math.floor((tick - slot - 1) / slots) + 1 : 0;
    return (slot + cutsHere * slots) % images;
  });
}

const REDUCE_QUERY = "(prefers-reduced-motion: reduce)";

export type IntroMotion = {
  /** False under prefers-reduced-motion: no doves, no control, one still collage. */
  motionOk: boolean;
  paused: boolean;
  setPaused: (paused: boolean) => void;
  /** Motion may run right now: allowed, tab visible and not paused. */
  live: boolean;
};

export function useIntroMotion(): IntroMotion {
  const [reduced, setReduced] = useState(true);
  const [visible, setVisible] = useState(false);
  const [paused, setPaused] = useState(false);

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const reduce = window.matchMedia(REDUCE_QUERY);
    const update = () => {
      setReduced(reduce.matches);
      setVisible(document.visibilityState !== "hidden");
    };
    update();
    reduce.addEventListener("change", update);
    document.addEventListener("visibilitychange", update);
    return () => {
      reduce.removeEventListener("change", update);
      document.removeEventListener("visibilitychange", update);
    };
  }, []);

  return {
    motionOk: !reduced,
    paused,
    setPaused,
    live: brandMotionAllowed({
      motion: !paused,
      reducedMotion: reduced,
      visible,
      inView: true,
    }),
  };
}
