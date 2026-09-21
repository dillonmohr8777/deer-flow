"use client";

import { useState } from "react";

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
 * Only names with a confident, verified fit are mapped here. Everything else
 * falls through to MomentumGlyph, which is correct today regardless: the
 * momos/ directory ships empty (see AVAILABLE_MOMO_SLUGS below), so every
 * agent renders the procedural glyph until artwork lands.
 *
 * Verified against the live roster in fleet/agents/*\/config.yaml (the only
 * concrete agent roster in this repo — there is no "dillon-" prefixed
 * lead/architect/brand/client-success/revenue/critic roster anywhere in the
 * codebase). Of the ten intended slugs, four have a confident live-name fit:
 *   analytics-engineer      -> analytics
 *   data-migration-engineer -> migration
 *   independent-verifier    -> verifier
 *   fleet-scout             -> research
 * "lead" is not roster-driven (agent-topology.tsx always seeds it from
 * leadLabel, not from a roster entry). The remaining slugs — architect,
 * brand, client-success, revenue, critic — and the remaining roster names —
 * fleet-builder, fleet-qa, fleet-reliability, senior-software-engineer —
 * have no confident match today and are intentionally left unmapped.
 */
const SLUG_MAP: Record<string, string> = {
  "analytics-engineer": "analytics",
  "data-migration-engineer": "migration",
  "independent-verifier": "verifier",
  "fleet-scout": "research",
};

// ponytail: manual manifest instead of a build-time fs glob of momos/. The
// directory ships empty by spec, so this starts empty and stays correct
// (glyph fallback, no request ever fired for a missing file — no 404).
// When artwork lands for a slug, add it here; add a fs-glob manifest only if
// this list grows unwieldy to hand-maintain.
const AVAILABLE_MOMO_SLUGS: ReadonlySet<string> = new Set([]);

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
  className,
}: {
  agent: MomoAvatarAgent;
  size?: number;
  sizeBucket?: MomoSizeBucket;
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
  const showImage = slug !== null && AVAILABLE_MOMO_SLUGS.has(slug) && !imgFailed;

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
          onError={() => setImgFailed(true)}
        />
      ) : (
        <MomentumGlyph seed={seed} size={size} className={styles.art} />
      )}
    </span>
  );
}
