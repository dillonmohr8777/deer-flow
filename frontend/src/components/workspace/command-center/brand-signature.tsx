"use client";

import Image from "next/image";
import { useEffect, useRef, useState } from "react";

import { brandMotionAllowed } from "./appearance-preferences";
import { useWorkspaceAppearance } from "./appearance-provider";

import styles from "./workspace-appearance.module.css";

/** One brand treatment across the dashboard and workspace navigation. */
export function BrandSignature({
  size = "compact",
}: {
  size?: "compact" | "hero";
}) {
  const { preferences, reducedMotion, visible } = useWorkspaceAppearance();
  const element = useRef<HTMLDivElement>(null);
  const [inView, setInView] = useState(false);
  useEffect(() => {
    if (!element.current || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(([entry]) => {
      setInView(Boolean(entry?.isIntersecting));
    });
    observer.observe(element.current);
    return () => observer.disconnect();
  }, []);
  const custom = Boolean(preferences.logo ?? preferences.label.trim());
  const label = preferences.label.trim() || "Your brand";
  return (
    <div
      ref={element}
      className={styles.signature}
      data-size={size}
      data-treatment={preferences.treatment}
      data-animated={brandMotionAllowed({
        motion: preferences.motion && preferences.treatment !== "classic",
        reducedMotion,
        visible,
        inView,
      })}
      data-custom={custom}
    >
      <span className={styles.backPlane} aria-hidden="true" />
      <span className={styles.middlePlane} aria-hidden="true" />
      <div className={styles.brandPlane}>
        {custom ? (
          <>
            {preferences.logo && (
              <Image
                className={styles.customLogo}
                src={preferences.logo}
                width={128}
                height={128}
                alt=""
                unoptimized
              />
            )}
            <span className={styles.customLabel} title={label}>
              {label}
            </span>
          </>
        ) : (
          <>
            {size === "hero" && (
              <Image
                className={styles.momo}
                src="/momentum/momo-mark.svg"
                width={72}
                height={79}
                alt="Momo, Momentum’s brand character"
              />
            )}
            <Image
              className={styles.wordmark}
              src="/momentum/wordmark.png"
              alt="Momentum"
              width={800}
              height={172}
              priority
            />
          </>
        )}
      </div>
    </div>
  );
}
