"use client";

import { useState } from "react";

import { brandMotionAllowed } from "./appearance-preferences";
import { useWorkspaceAppearance } from "./appearance-provider";
import { MomentumGlyph } from "./momentum-glyph";

import styles from "./momo-avatar.module.css";

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
// by scripts/generate-momos.mjs (dillon-brain is hand-authored, not
// generated: it is not a robot Momo) — a slug listed without its file would
// fire a 404 before onError fell back to the glyph. Add a fs-glob manifest
// only if this list grows unwieldy to hand-maintain.
const AVAILABLE_MOMO_SLUGS: ReadonlySet<string> = new Set([
  "analytics",
  "builder",
  "client-success",
  "dillon-brain",
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
  className,
}: {
  agent: MomoAvatarAgent;
  size?: number;
  sizeBucket?: MomoSizeBucket;
  /**
   * True while this agent has a recorded active run. Only Dillon Brain reads
   * it, for the faster/stronger pulse; omit it where that state is unknown,
   * which simply keeps the gentle pulse.
   */
  active?: boolean;
  className?: string;
}) {
  const [imgFailed, setImgFailed] = useState(false);
  const { preferences, reducedMotion, visible } = useWorkspaceAppearance();
  const bucket = sizeBucket ?? bucketFor(size);
  const seed = `agent:${agent.name}`;
  const slug = slugFor(agent.name);
  const label = agent.display_name ?? agent.name;
  const accessibleName = agent.description
    ? `${label}, ${agent.description}`
    : label;
  const showImage = slug !== null && AVAILABLE_MOMO_SLUGS.has(slug) && !imgFailed;
  // Dillon Brain's pulse: prefers-reduced-motion and the app's own motion
  // switch (brandMotionAllowed) both make it fully static.
  const pulse =
    slug === "dillon-brain" &&
    brandMotionAllowed({ motion: preferences.motion, reducedMotion, visible, inView: true });

  return (
    <span
      className={[styles.avatar, className].filter(Boolean).join(" ")}
      data-size={bucket}
      role="img"
      aria-label={accessibleName}
    >
      {showImage ? (
        <img
          className={styles.art}
          src={`/momentum/momos/${slug}.svg`}
          alt=""
          aria-hidden="true"
          width={size}
          height={size}
          data-slug={slug}
          data-motion={pulse ? "on" : undefined}
          data-active={pulse && active ? "true" : undefined}
          onError={() => setImgFailed(true)}
        />
      ) : (
        <MomentumGlyph
          seed={seed}
          size={size}
          initial={label}
          className={styles.art}
        />
      )}
    </span>
  );
}
