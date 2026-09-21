import { useId } from "react";

const paths = [
  "M12 24c0-7 5-12 12-12s12 5 12 12-5 12-12 12",
  "M10 29c5 0 6-18 14-18s9 18 14 18M14 35h20",
  "M11 17c7-7 19-7 26 0L24 38 11 17Z",
  "M12 33c4-15 20-15 24 0M15 16c6 5 12 5 18 0",
  "M11 24h26M24 11v26M15 15l18 18M33 15 15 33",
  "M10 30c8 0 8-19 16-19 7 0 7 14 12 14M14 36c7-8 13-8 20 0",
  "M12 16c5-6 19-6 24 0-3 6-7 9-12 9s-9-3-12-9ZM16 33c5-4 11-4 16 0",
  "M11 28c4-13 10-17 13-17s9 4 13 17c-8-4-18-4-26 0ZM16 35h16",
] as const;

const accents = [
  "#075bd8",
  "#008fc9",
  "#5b3bd8",
  "#087d62",
  "#c73570",
  "#3157d5",
] as const;

function hashSeed(seed: string) {
  let hash = 2166136261;
  for (let index = 0; index < seed.length; index += 1) {
    hash ^= seed.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

export function MomentumGlyph({
  seed,
  size = 40,
  label,
  className,
}: {
  seed: string;
  size?: number;
  label?: string;
  className?: string;
}) {
  const hash = hashSeed(seed);
  const path = paths[hash % paths.length];
  const accent = accents[(hash >>> 4) % accents.length];
  const rotation = ((hash >>> 8) % 12) * 30;
  const node = 12 + ((hash >>> 12) % 25);
  const gradientId = `momentum-${useId().replaceAll(":", "")}`;
  const signature = `${hash % paths.length}-${(hash >>> 4) % accents.length}-${rotation}-${node}`;

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
      <defs>
        <linearGradient id={gradientId} x1="8" y1="8" x2="40" y2="40">
          <stop stopColor="#0878ff" />
          <stop offset="0.55" stopColor={accent} />
          <stop offset="1" stopColor="#b7edff" />
        </linearGradient>
      </defs>
      <circle cx="24" cy="24" r="21" fill="#eef8ff" />
      <circle cx="24" cy="24" r="19.5" stroke="#b9dcf5" />
      <g transform={`rotate(${rotation} 24 24)`}>
        <path
          d={path}
          stroke={`url(#${gradientId})`}
          strokeWidth="3.2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <circle cx={node} cy="24" r="2.8" fill={accent} />
      </g>
    </svg>
  );
}
