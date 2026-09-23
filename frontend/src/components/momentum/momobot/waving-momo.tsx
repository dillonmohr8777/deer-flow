"use client";

import { useEffect, useState } from "react";

import { BLINK_FRAME, BLINK_MS, waveTimeline } from "./intro-motion";

import styles from "./momobot.module.css";

/*
 * Momo peeking over the top right of the sign-in sheet, hands on its edge.
 * One sprite (public/momentum/momobot/login-wave.webp): four aligned wave
 * frames plus a closed-eye frame. He waves on load and whenever `cue`
 * changes (hover or focus of the email field), and blinks now and then while
 * idle. When `live` is false (reduced motion, hidden tab, paused) he holds
 * frame 0.
 */
export function WavingMomo({ live, cue }: { live: boolean; cue: number }) {
  const [frame, setFrame] = useState(0);

  useEffect(() => {
    if (!live) {
      setFrame(0);
      return;
    }
    const steps = waveTimeline();
    let index = 0;
    let timer: number | undefined;
    const step = () => {
      const current = steps[index];
      if (!current) return;
      setFrame(current.frame);
      index += 1;
      if (index < steps.length) timer = window.setTimeout(step, current.ms);
    };
    step();
    return () => window.clearTimeout(timer);
  }, [live, cue]);

  useEffect(() => {
    if (!live) return;
    let open: number | undefined;
    let close: number | undefined;
    const schedule = () => {
      open = window.setTimeout(
        () => {
          setFrame((value) => (value === 0 ? BLINK_FRAME : value));
          close = window.setTimeout(() => {
            setFrame((value) => (value === BLINK_FRAME ? 0 : value));
            schedule();
          }, BLINK_MS);
        },
        3200 + Math.random() * 3000,
      );
    };
    schedule();
    return () => {
      window.clearTimeout(open);
      window.clearTimeout(close);
    };
  }, [live]);

  return (
    <div
      className={styles.momo}
      data-frame={frame}
      aria-hidden="true"
      style={{ backgroundPositionX: `${frame * 25}%` }}
    />
  );
}
