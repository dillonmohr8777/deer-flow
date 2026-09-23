"use client";

/*
 * Reusable 2.5D "paper layers" treatment: stacked cut-paper images inside a
 * `perspective` container, each on its own translateZ plane. Desktop
 * hover/pointer motion tilts the stack (CSS vars written imperatively on
 * pointermove, never React state, so hover never re-renders); a "working"
 * state lifts every layer but the base a few px with a deepening drop
 * shadow, matching the reference prototype
 * (Documents/Qwen/block-shots/2026-09-23-brain-v2/proto.html).
 *
 * Below 40px, or whenever motion is not allowed (prefers-reduced-motion or
 * the workspace's own appearanceMotion switch is off), this renders nothing
 * but the flattened fallback image: no stage, no layers, no listeners.
 */

import { useCallback, useRef, type PointerEvent as ReactPointerEvent } from "react";

import { brandMotionAllowed } from "@/components/workspace/command-center/appearance-preferences";
import { useWorkspaceAppearance } from "@/components/workspace/command-center/appearance-provider";

import styles from "./paper-layers.module.css";

const FLAT_BELOW_PX = 40;
const MAX_TILT_DEG = 12;

export type PaperLayersState = "idle" | "working";

export function PaperLayers({
  layers,
  flatSrc,
  size,
  aspectRatio = 1,
  alt = "",
  state = "idle",
  className,
}: {
  /** Ordered back-to-front image srcs; index 0 sits nearest the surface, the last one on top. */
  layers: readonly string[];
  /** Single flattened composite: used below 40px and whenever motion is not allowed. */
  flatSrc: string;
  size: number;
  /** height / width of the artwork. 1 for the square Momos; ~0.878 for Dillon Brain. */
  aspectRatio?: number;
  /** Only the top layer (or the flat fallback) carries this; the rest stay aria-hidden. */
  alt?: string;
  state?: PaperLayersState;
  className?: string;
}) {
  const stageRef = useRef<HTMLDivElement>(null);
  const { preferences, reducedMotion, visible } = useWorkspaceAppearance();
  const motionAllowed = brandMotionAllowed({
    motion: preferences.motion,
    reducedMotion,
    visible,
    inView: true,
  });
  const height = Math.round(size * aspectRatio);

  const handlePointerMove = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.pointerType !== "mouse") return;
    const node = stageRef.current;
    if (!node) return;
    const rect = node.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const px = (event.clientX - rect.left) / rect.width - 0.5;
    const py = (event.clientY - rect.top) / rect.height - 0.5;
    node.style.setProperty("--pl-tilt-y", `${(px * 2 * MAX_TILT_DEG).toFixed(2)}deg`);
    node.style.setProperty("--pl-tilt-x", `${(-py * 2 * MAX_TILT_DEG).toFixed(2)}deg`);
  }, []);

  const handlePointerLeave = useCallback(() => {
    const node = stageRef.current;
    if (!node) return;
    node.style.setProperty("--pl-tilt-y", "0deg");
    node.style.setProperty("--pl-tilt-x", "0deg");
  }, []);

  // ponytail: one flat-image branch covers both "too small to read layers"
  // and "motion is not allowed" — fully static is fully static either way.
  if (size < FLAT_BELOW_PX || !motionAllowed) {
    return (
      <img
        className={[styles.flat, className].filter(Boolean).join(" ")}
        data-paper-layers="root"
        src={flatSrc}
        alt={alt}
        aria-hidden={alt ? undefined : true}
        width={size}
        height={height}
        draggable={false}
      />
    );
  }

  return (
    <div
      className={[styles.perspective, className].filter(Boolean).join(" ")}
      data-paper-layers="root"
      style={{ width: size, height }}
    >
      <div
        ref={stageRef}
        className={styles.stage}
        data-state={state}
        onPointerMove={handlePointerMove}
        onPointerLeave={handlePointerLeave}
      >
        {layers.map((src, index) => {
          const isTop = index === layers.length - 1;
          return (
            <img
              key={src}
              className={styles.layer}
              data-depth={index}
              src={src}
              alt={isTop ? alt : ""}
              aria-hidden={isTop && alt ? undefined : true}
              draggable={false}
            />
          );
        })}
      </div>
    </div>
  );
}
