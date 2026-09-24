"use client";

import { PaperLayers } from "@/components/momentum/paper-layers";
import {
  REPORTERS,
  reporterLayers,
  type ReporterSlug,
} from "@/core/momo-daily";

/** A living cut-paper Momo in its role as one of the paper's reporters. */
export function Reporter({
  slug,
  size,
  motion,
  className,
}: {
  slug: ReporterSlug;
  size: number;
  motion: boolean;
  className?: string;
}) {
  const { layers, flatSrc } = reporterLayers(slug);
  return (
    <PaperLayers
      className={className}
      layers={layers}
      flatSrc={flatSrc}
      size={size}
      alt={`${REPORTERS[slug]} desk reporter Momo`}
      motionAllowed={motion}
    />
  );
}
