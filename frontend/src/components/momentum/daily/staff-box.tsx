"use client";

import { useEffect, useId, useRef, useState } from "react";

import styles from "./daily.module.css";

/*
 * The portraits are private and never committed: public/momentum/daily/people/
 * is gitignored. A deploy without them, or any single missing file, shows the
 * engraved Momo instead of a broken image.
 */
export const STAFF = [
  { slug: "sean-boyle", name: "Sean Boyle", title: "Managing Partner" },
  { slug: "dillon-mohr", name: "Dillon Mohr", title: "AI Marketing Director" },
  { slug: "jason-fallon", name: "Jason Fallon", title: "VP of Sales" },
  {
    slug: "jenny-mcclain-miller",
    name: "Jenny McClain Miller",
    title: "Director of Content",
  },
  { slug: "mac-frederick", name: "Mac Frederick", title: "Google Guru" },
  { slug: "melissa-rigby", name: "Melissa Rigby", title: "" },
  { slug: "beth-kann", name: "Beth Kann", title: "" },
] as const;

export function portraitSrc(slug: string) {
  return `/momentum/daily/people/${slug}.webp`;
}

/** A Momo cut as a copperplate engraving: ink line and hatching, no colour. */
export function EngravedMomo({ label }: { label: string }) {
  // Unique pattern ids: several placeholders can share a page.
  const id = `daily-hatch-${useId().replace(/[^a-zA-Z0-9]/g, "")}`;
  return (
    <svg
      className={styles.engraved}
      viewBox="0 0 120 132"
      role="img"
      aria-label={label}
      data-portrait="placeholder"
    >
      <defs>
        <pattern
          id={id}
          width="4"
          height="4"
          patternUnits="userSpaceOnUse"
          patternTransform="rotate(35)"
        >
          <line
            x1="0"
            y1="0"
            x2="0"
            y2="4"
            stroke="currentColor"
            strokeWidth="1.1"
          />
        </pattern>
        <pattern
          id={`${id}-fine`}
          width="3"
          height="3"
          patternUnits="userSpaceOnUse"
          patternTransform="rotate(-40)"
        >
          <line
            x1="0"
            y1="0"
            x2="0"
            y2="3"
            stroke="currentColor"
            strokeWidth="0.5"
          />
        </pattern>
      </defs>
      <path
        d="M60 29V15"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
      />
      <circle
        cx="60"
        cy="11"
        r="5"
        fill={`url(#${id}-fine)`}
        stroke="currentColor"
        strokeWidth="1.4"
      />
      <path
        d="M60 28c30 0 49 20 49 49s-18 47-49 47S11 106 11 77s19-49 49-49Z"
        fill={`url(#${id})`}
        stroke="currentColor"
        strokeWidth="2"
      />
      <path
        d="M22 70c4-20 20-33 38-33"
        fill="none"
        stroke="var(--paper-cream-hi)"
        strokeWidth="5"
        strokeLinecap="round"
      />
      <rect
        x="35"
        y="59"
        width="12"
        height="23"
        rx="6"
        fill="var(--paper-cream-hi)"
        stroke="currentColor"
        strokeWidth="1.6"
      />
      <rect
        x="73"
        y="59"
        width="12"
        height="23"
        rx="6"
        fill="var(--paper-cream-hi)"
        stroke="currentColor"
        strokeWidth="1.6"
      />
    </svg>
  );
}

export function StaffPortrait({ slug, name }: { slug: string; name: string }) {
  const [missing, setMissing] = useState(false);
  const imgRef = useRef<HTMLImageElement>(null);

  // A server-rendered <img> can fail before React attaches onError; catch
  // that case on mount too.
  useEffect(() => {
    const img = imgRef.current;
    if (img?.complete && img.naturalWidth === 0) setMissing(true);
  }, []);

  if (missing)
    return <EngravedMomo label={`Engraving placeholder for ${name}`} />;
  return (
    <img
      ref={imgRef}
      className={styles.portrait}
      src={portraitSrc(slug)}
      alt={`Engraved portrait of ${name}`}
      width={160}
      height={160}
      loading="lazy"
      data-portrait="photo"
      onError={() => setMissing(true)}
    />
  );
}

export function StaffBox() {
  return (
    <section className={styles.staff} aria-labelledby="daily-staff-heading">
      <h2 id="daily-staff-heading" className={styles.staffHeading}>
        The Staff
      </h2>
      <p className={styles.staffKicker}>Momentum, Philadelphia</p>
      <ul className={styles.staffGrid}>
        {STAFF.map((person) => (
          <li key={person.slug} className={styles.staffCard}>
            <div className={styles.portraitFrame}>
              <StaffPortrait slug={person.slug} name={person.name} />
            </div>
            <p className={styles.staffName}>{person.name}</p>
            {person.title ? (
              <p className={styles.staffTitle}>{person.title}</p>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}
