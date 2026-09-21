"use client";

/*
 * Cut-paper headline word: per-letter ±1.5deg jitter, settling in once,
 * 380ms with a 40ms stagger. Screen readers get one clean word — the
 * wrapper carries the accessible name via aria-label, and every per-letter
 * span is aria-hidden so nothing is announced letter by letter.
 *
 * "background-clip: text over a collage tile" is the brief's undegraded
 * look; the caller supplies that tile as a background on `className`. No
 * approved collage art exists yet that stays within the brass/cyan
 * text-contrast ban (paper.css: both are object-only, 2.10/2.28 on cream —
 * never text), so momentum-landing.tsx currently renders the degrade path:
 * solid --paper-ink text at 14.07:1, which this component already produces
 * with no collage background set. Swap in a collage `className` once art
 * lands; the per-letter/aria/motion mechanics here don't change.
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
  const [settled, setSettled] = useState(false);

  useEffect(() => {
    const node = wrapperRef.current;
    if (!node) return;
    const reducedMotionQuery = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    );

    const tryReveal = (inView: boolean) => {
      if (settled) return;
      if (
        brandMotionAllowed({
          motion: true,
          reducedMotion: reducedMotionQuery.matches,
          visible: document.visibilityState === "visible",
          inView,
        })
      ) {
        setSettled(true);
      } else if (reducedMotionQuery.matches) {
        // Motion fully off: skip straight to the resting state, no reveal.
        setSettled(true);
      }
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const letters = [...word];
  const reduceMotion =
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  return (
    <span ref={wrapperRef} className={className} aria-label={word}>
      {letters.map((letter, index) => (
        <span
          key={index}
          aria-hidden="true"
          className={letterClassName}
          style={{
            display: "inline-block",
            transform:
              settled || reduceMotion
                ? `rotate(${jitterDeg(index, letter)}deg)`
                : "rotate(0deg) translateY(0.4em)",
            opacity: settled || reduceMotion ? 1 : 0,
            transition:
              settled && !reduceMotion
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
