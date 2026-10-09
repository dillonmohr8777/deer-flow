"use client";

import { useEffect, useState } from "react";

import { brandMotionAllowed } from "@/components/workspace/command-center/appearance-preferences";

/** The 3D paper only ever plays on a wide screen with a fine pointer. */
export const DAILY_DESKTOP_QUERY = "(min-width: 900px) and (pointer: fine)";
const REDUCE_QUERY = "(prefers-reduced-motion: reduce)";

/*
 * The Daily is public, so it sits outside the workspace appearance provider
 * (whose default reads as "no motion"). It asks brandMotionAllowed() the
 * same question with what a signed-out page can know: the OS motion
 * preference and tab visibility. Phones never get 3D. Server render and
 * first paint are always motion-off, so nothing animates before hydration.
 */
export function useDailyMotion(): boolean {
  const [allowed, setAllowed] = useState(false);

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const reduce = window.matchMedia(REDUCE_QUERY);
    const desktop = window.matchMedia(DAILY_DESKTOP_QUERY);
    const update = () =>
      setAllowed(
        desktop.matches &&
          brandMotionAllowed({
            motion: true,
            reducedMotion: reduce.matches,
            visible: document.visibilityState !== "hidden",
            inView: true,
          }),
      );
    update();
    reduce.addEventListener("change", update);
    desktop.addEventListener("change", update);
    document.addEventListener("visibilitychange", update);
    return () => {
      reduce.removeEventListener("change", update);
      desktop.removeEventListener("change", update);
      document.removeEventListener("visibilitychange", update);
    };
  }, []);

  return allowed;
}
