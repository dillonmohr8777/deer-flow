/*
 * Identity mark for anything without shipped artwork: unmapped agents, threads,
 * system rows.
 *
 * The previous version generated geometry — an arbitrary path, rotated to an
 * arbitrary angle, stroked with a gradient, over two unrelated decorative arcs,
 * with a dot of a random accent colour parked at a random position on the
 * centreline. Six free variables combining without constraint, so most seeds
 * landed on a bad composition, and the accent set (magenta, purple) fought the
 * blue it was drawn over. Gradients and those accents are also exactly what
 * paper.css exists to keep out.
 *
 * This generates identity instead of geometry. The silhouette is fixed — the
 * same deckle-edged disc the shipped Momos use, so mapped and unmapped agents
 * read as one family — and the seed only chooses between hand-drawn marks that
 * are each composed on purpose. Callers with a real name pass `initial` and get
 * a monogram, which beats any abstract mark for telling two agents apart.
 */

const INK = "#101e3f";
const CREAM = "#fbf8f1";
const BRASS = "#c8a04a";

/**
 * Identical to the disc in scripts/generate-momos.mjs. Pinned by
 * tests/unit/components/workspace/momo-manifest.test.ts so the fallback and the
 * shipped artwork can never drift into two different silhouettes.
 */
const DISC =
  "M24.00 3.60L28.83 2.85L32.89 5.55L37.21 7.44L40.36 10.95L42.95 14.87L44.74 19.27L44.63 24.00L44.34 28.64L43.06 33.18L41.01 37.57L37.44 40.85L32.96 42.61L28.85 45.25L24.00 45.54L19.32 44.49L14.59 43.55L10.90 40.42L7.35 37.28L5.21 33.05L3.07 28.78L2.82 24.00L3.21 19.25L5.09 14.89L7.90 11.16L10.99 7.69L14.85 5.00L19.46 4.11Z";

const STROKE = {
  fill: "none",
  stroke: CREAM,
  strokeWidth: 2.6,
  strokeLinecap: "round",
  strokeLinejoin: "round",
} as const;

/*
 * Every mark is drawn on purpose, so any seed lands on a composed result.
 * Deliberately no plus and no saltire: on an avatar those read as "add" and
 * "delete" rather than as an identity.
 */
const MARKS: readonly string[] = [
  "M15 29.5 21 20l4.6 6.2L33 15.5", // climb
  "M16.5 18.5 23 24l-6.5 5.5M27 18.5 33.5 24 27 29.5", // inward chevrons
  "M16 24h0M24 24h0M32 24h0", // three dots (round caps)
  "M15 20h18M15 28h18", // two rules
  "M24 14.6 33.4 31H14.6Z", // triangle
  "M13.8 27.6c4.2-9.6 16.2-9.6 20.4 0", // arc
  "M17 30V22M24 30V16M31 30v-5.6", // three bars
  "M13.6 26.4c3-6 5.8-6 8.8 0s5.8 6 8.8 0", // wave
  "M24 13.8 34.2 24 24 34.2 13.8 24Z", // diamond
  "M14.6 22c5-6 13.8-6 18.8 0M14.6 29c5-6 13.8-6 18.8 0", // stacked arcs
];

function hashSeed(seed: string) {
  let hash = 2166136261;
  for (let index = 0; index < seed.length; index += 1) {
    hash ^= seed.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

/** First letter of a human label. Returns null when there is nothing to show. */
function monogramOf(initial: string | undefined) {
  if (!initial) return null;
  const letters = [...initial].filter((character) => /[\p{L}\p{N}]/u.test(character));
  return letters.length ? letters[0]!.toUpperCase() : null;
}

export function MomentumGlyph({
  seed,
  size = 40,
  label,
  initial,
  className,
}: {
  seed: string;
  size?: number;
  label?: string;
  /** A human name. Given one, the glyph shows its first letter instead of a mark. */
  initial?: string;
  className?: string;
}) {
  const hash = hashSeed(seed);
  const markIndex = hash % MARKS.length;
  const monogram = monogramOf(initial);
  // Four resting angles rather than twelve free ones: enough to tell two discs
  // apart, never enough to look knocked over.
  const pinAngle = [-34, -14, 14, 34][(hash >>> 8) % 4]!;
  const pinX = 24 + Math.sin((pinAngle * Math.PI) / 180) * 17.4;
  const pinY = 24 - Math.cos((pinAngle * Math.PI) / 180) * 17.4;
  const signature = `${monogram ?? markIndex}-${pinAngle}`;

  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 48 48"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      data-momentum-glyph={signature}
    >
      <path d={DISC} fill={INK} />
      {monogram ? (
        <text
          x="24"
          y="24"
          textAnchor="middle"
          dominantBaseline="central"
          fill={CREAM}
          fontSize="21"
          fontWeight="700"
          fontFamily="var(--font-paper-display, Georgia, 'Times New Roman', serif)"
        >
          {monogram}
        </text>
      ) : (
        <path d={MARKS[markIndex]} {...STROKE} />
      )}
      {size > 48 ? (
        <>
          <circle cx={pinX} cy={pinY} r="2.5" fill={BRASS} />
          <circle cx={pinX - 0.7} cy={pinY - 0.8} r="0.8" fill={CREAM} opacity="0.55" />
        </>
      ) : null}
    </svg>
  );
}
