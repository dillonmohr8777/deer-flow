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

/**
 * Cream scrim over the collage under the landing hero copy. Pinned by a
 * contrast test: ink and muted ink stay at 4.5:1 or better over any frame.
 * The collage film's biggest luminance jumps land about once a second, under
 * the three-per-second flash limit, and the scrim softens them further.
 */
export const LANDING_SCRIM_ALPHA = 0.86;
const REDUCE_QUERY = "(prefers-reduced-motion: reduce)";

export type IntroMotion = {
  /** False under prefers-reduced-motion: no doves, no control, a still collage. */
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
