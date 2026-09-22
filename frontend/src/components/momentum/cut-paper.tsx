"use client";

/*
 * Cut-paper headline word: per-letter ±1.5deg jitter, settling in once,
 * 380ms with a 40ms stagger. Screen readers get one clean word — the
 * wrapper carries the accessible name via aria-label, and every per-letter
 * span is aria-hidden so nothing is announced letter by letter.
 *
 * "background-clip: text over a collage tile" is the brief's undegraded
 * look; the caller supplies that tile as a background on `className`.
 * momentum-landing.tsx now passes .paperCutWordCollage, which fills the word
 * with collage-navy.png (measured: mean 13.02:1 on cream, worst pixel 4.52:1,
 * nothing below AA large). That fill is applied only inside an @supports
 * guard, so anywhere background-clip is missing this component still renders
 * its degrade path: solid --paper-ink at 14.07:1, which is what it produces
 * with no collage background set. The per-letter, aria and motion mechanics
 * here are the same either way.
 */

import { useEffect, useRef, useState } from "react";

import { brandMotionAllowed } from "@/components/workspace/command-center/appearance-preferences";

const SETTLE_MS = 380;
const STAGGER_MS = 40;

// Deterministic per-letter rotation so server and client markup match on
// hydration — Math.random() would mismatch and trip a hydration warning.
function jitterDeg(index: number, letter: string): number {
  const code = letter.codePointAt(0) ?? index;
  const step = ((code * 31 + index * 17) % 61) - 30; // -30..30
  return Number(((step / 30) * 1.5).toFixed(2)); // -1.5deg..1.5deg
}

export function CutPaper({
  word,
  className,
  letterClassName,
}: {
  word: string;
  className?: string;
  letterClassName?: string;
}) {
  const wrapperRef = useRef<HTMLSpanElement>(null);
  const [reveal, setReveal] = useState<null | "animate" | "instant">(null);

  useEffect(() => {
    const node = wrapperRef.current;
    if (!node) return;
    const reducedMotionQuery = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    );

    // Reaching the viewport always reveals. `brandMotionAllowed` decides only
    // HOW the word arrives, never WHETHER it is there: gating visibility on it
    // left the headline permanently at opacity 0 whenever the tab was
    // backgrounded at load (visible: false), because the observer disconnected
    // on that same first intersection and nothing ever retried.
    const tryReveal = (inView: boolean) => {
      if (!inView) return;
      setReveal(
        (current) =>
          current ??
          (brandMotionAllowed({
            motion: true,
            reducedMotion: reducedMotionQuery.matches,
            visible: document.visibilityState === "visible",
            inView,
          })
            ? "animate"
            : "instant"),
      );
    };

    if (!("IntersectionObserver" in window)) {
      tryReveal(true);
      return;
    }

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting) {
          tryReveal(true);
          observer.disconnect();
        }
      },
      { threshold: 0.4 },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  const letters = [...word];
  const shown = reveal !== null;
  const animating = reveal === "animate";

  return (
    <span ref={wrapperRef} className={className} aria-label={word}>
      {letters.map((letter, index) => (
        <span
          key={index}
          aria-hidden="true"
          className={letterClassName}
          style={{
            display: "inline-block",
            transform: shown
              ? `rotate(${jitterDeg(index, letter)}deg)`
              : "rotate(0deg) translateY(0.4em)",
            opacity: shown ? 1 : 0,
            transition: animating
              ? `transform ${SETTLE_MS}ms cubic-bezier(0.16, 1, 0.3, 1) ${
                  index * STAGGER_MS
                }ms, opacity ${SETTLE_MS}ms ease ${index * STAGGER_MS}ms`
              : "none",
          }}
        >
          {letter === " " ? " " : letter}
        </span>
      ))}
    </span>
  );
}
