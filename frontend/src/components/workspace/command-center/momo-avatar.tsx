"use client";

import { useState } from "react";

import { PaperLayers } from "@/components/momentum/paper-layers";

import { MomentumGlyph } from "./momentum-glyph";

import styles from "./momo-avatar.module.css";

// Dillon Brain's paper layers (kraft -> body -> folds), converted from the
// reference prototype at Documents/Qwen/block-shots/2026-09-23-brain-v2/.
// Not part of AVAILABLE_MOMO_SLUGS below: it is a hand-authored PaperLayers
// composition, not a robot Momo svg loaded by slug. Exported so other
// surfaces that draw Dillon Brain outside MomoAvatar (the Command Center
// hero crew) use the same files rather than a second copy of the paths.
export const BRAIN_LAYERS = [
  "/momentum/brain/kraft.webp",
  "/momentum/brain/body.webp",
  "/momentum/brain/folds.webp",
] as const;
export const BRAIN_FLAT = "/momentum/brain/flat.webp";
export const BRAIN_ASPECT = 422 / 480;

export type MomoAvatarAgent = {
  name: string;
  display_name?: string | null;
  description?: string;
};

export type MomoSizeBucket = "sm" | "md" | "lg";

/**
 * Roster `agent.name` -> shipped Momo slug (public/momentum/momos/<slug>.svg).
 * Only names with a confident fit are mapped here. Everything else falls
 * through to MomentumGlyph.
 *
 * Two rosters feed this: the fleet definitions in fleet/agents/*\/config.yaml
 * and the managed subagents the Command Center lists from /api/subagents
 * (dillon-* and momentum-*). "dillon-brain" is the lead agent's real name,
 * seeded wherever the Command Center draws the lead's card. "lead" is kept
 * mapped for compatibility but nothing in the app passes it any more. Every
 * known name has canon art; only names nobody has mapped yet fall back to
 * the glyph.
 */
const SLUG_MAP: Record<string, string> = {
  "analytics-engineer": "analytics",
  "data-migration-engineer": "migration",
  "independent-verifier": "verifier",
  "fleet-scout": "research",
  "fleet-builder": "builder",
  "fleet-qa": "qa",
  "fleet-reliability": "reliability",
  "senior-software-engineer": "engineer",
  lead: "lead",
  "dillon-brain": "dillon-brain",
  "dillon-builder": "builder",
  "dillon-client-operations": "client-success",
  "dillon-critic": "qa",
  "dillon-growth": "growth",
  "dillon-revenue": "revenue",
  "dillon-reliability": "reliability",
  "dillon-intelligence": "research",
  "momentum-independent-verifier": "verifier",
  "momentum-analytics-engineer": "analytics",
  "momentum-solutions-architect": "engineer",
  "momentum-migration-engineer": "migration",
};

// ponytail: manual manifest instead of a build-time fs glob of momos/. Every
// slug here must have a matching public/momentum/momos/<slug>.svg, generated
// by scripts/generate-momos.mjs — a slug listed without its file would fire
// a 404 before onError fell back to the glyph. Add a fs-glob manifest only
// if this list grows unwieldy to hand-maintain. dillon-brain is handled
// separately below, as a PaperLayers composition, not a robot Momo svg.
const AVAILABLE_MOMO_SLUGS: ReadonlySet<string> = new Set([
  "analytics",
  "builder",
  "client-success",
  "engineer",
  "growth",
  "lead",
  "migration",
  "qa",
  "reliability",
  "research",
  "revenue",
  "verifier",
]);

function slugFor(name: string): string | null {
  const bare = name.replace(/^dillon-/, "");
  return SLUG_MAP[name] ?? SLUG_MAP[bare] ?? null;
}

function bucketFor(size: number): MomoSizeBucket {
  if (size <= 48) return "sm";
  if (size <= 96) return "md";
  return "lg";
}

export function MomoAvatar({
  agent,
  size = 40,
  sizeBucket,
  active,
  decorative,
  className,
}: {
  agent: MomoAvatarAgent;
  size?: number;
  sizeBucket?: MomoSizeBucket;
  /**
   * True while this agent has a recorded active run. Only Dillon Brain reads
   * it today, for its PaperLayers "working" breathe; omit it where that
   * state is unknown, which simply keeps the stack still.
   */
  active?: boolean;
  /** The agent's name is already written beside the mark, so skip announcing it. */
  decorative?: boolean;
  className?: string;
}) {
  const [imgFailed, setImgFailed] = useState(false);
  const bucket = sizeBucket ?? bucketFor(size);
  const seed = `agent:${agent.name}`;
  const slug = slugFor(agent.name);
  const label = agent.display_name ?? agent.name;
  const accessibleName = agent.description
    ? `${label}, ${agent.description}`
    : label;
  const isBrain = slug === "dillon-brain";
  const showImage =
    !isBrain && slug !== null && AVAILABLE_MOMO_SLUGS.has(slug) && !imgFailed;

  return (
    <span
      className={[styles.avatar, className].filter(Boolean).join(" ")}
      data-size={bucket}
      role={decorative ? undefined : "img"}
      aria-label={decorative ? undefined : accessibleName}
      aria-hidden={decorative ? true : undefined}
    >
      {isBrain ? (
        // PaperLayers itself goes fully static under prefers-reduced-motion
        // or the workspace motion switch; "working" only ever requests the
        // breathe, never forces it.
        <PaperLayers
          className={styles.art}
          layers={BRAIN_LAYERS}
          flatSrc={BRAIN_FLAT}
          size={size}
          aspectRatio={BRAIN_ASPECT}
          state={active ? "working" : "idle"}
        />
      ) : showImage ? (
        <img
          className={styles.art}
          src={`/momentum/momos/${slug}.svg`}
          alt=""
          aria-hidden="true"
          width={size}
          height={size}
          data-slug={slug}
          onError={() => setImgFailed(true)}
        />
      ) : (
        <MomentumGlyph
          seed={seed}
          size={size}
          // From the stable name, not the display name: the mark must not
          // change letter when the agent record finishes loading.
          initial={agent.name}
          className={styles.art}
        />
      )}
    </span>
  );
}
