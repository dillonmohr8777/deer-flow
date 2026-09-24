import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

import styles from "./momobot.module.css";

/*
 * Momo, alive on the front door: a Momo film on a cream photo that floats and
 * bounces in 3D above a soft ground shadow. The film supplies the character's
 * own 3D motion; this adds only transform and opacity keyframes (no layout).
 * `live` is the front door's motion switch (useIntroMotion().live): when it is
 * false the bounce pauses where it stands, and prefers-reduced-motion removes
 * it entirely, leaving a still, slightly tilted photo and the film's poster.
 */
export function BouncingMomo({
  live,
  className,
  children,
}: {
  live: boolean;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div
      className={cn(styles.momoStage, className)}
      data-live={live}
      aria-hidden="true"
    >
      <div className={styles.momoFloat}>
        <div className={styles.momoCard}>{children}</div>
      </div>
      <span className={styles.momoGround} />
    </div>
  );
}
