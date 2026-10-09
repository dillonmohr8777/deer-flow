"use client";

import { useEffect, useRef } from "react";

/*
 * A short Momo film from public/momentum/films/<name>.{webm,mp4,webp}.
 * Muted, inline, never preloaded: the poster is all first paint costs. It
 * plays only while `live` (motion allowed, tab visible, not paused) and holds
 * the poster otherwise, so reduced motion gets a still Momo.
 */
export function MomoFilm({
  name,
  live,
  loop = true,
  className,
  onEnded,
}: {
  name: string;
  live: boolean;
  loop?: boolean;
  className?: string;
  onEnded?: () => void;
}) {
  const ref = useRef<HTMLVideoElement>(null);
  const base = `/momentum/films/${name}`;

  useEffect(() => {
    const video = ref.current;
    if (!video) return;
    if (live) {
      video.play().catch(() => undefined);
    } else {
      video.pause();
    }
  }, [live]);

  return (
    <video
      ref={ref}
      className={className}
      poster={`${base}.webp`}
      muted
      playsInline
      loop={loop}
      preload="none"
      aria-hidden="true"
      onEnded={onEnded}
    >
      <source src={`${base}.webm`} type="video/webm" />
      <source src={`${base}.mp4`} type="video/mp4" />
    </video>
  );
}
