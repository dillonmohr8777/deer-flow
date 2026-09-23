/*
 * Which funnel look the signed-out surfaces (`/`, `/login`, `/invite`) show.
 *
 * The Command Center's appearance provider (appearance-preferences.ts) is
 * mounted only inside /workspace and keyed per account, so a signed-out
 * visitor has no preference to read. FUNNEL_TREATMENT is the one-word
 * day-one default — flipping the funnel later is changing this one export.
 * `?look=paper` (or `?look=current`) previews either look without touching
 * the default, and works in both directions.
 */

export type FunnelTreatment = "current" | "paper";

export const FUNNEL_TREATMENT: FunnelTreatment = "paper";

const VALID_TREATMENTS: ReadonlySet<string> = new Set(["current", "paper"]);

/**
 * Resolves the treatment to render. Pass the query string explicitly when
 * you have one (e.g. from `useSearchParams()`); otherwise it reads
 * `window.location.search` when available and falls back to
 * FUNNEL_TREATMENT during SSR/the first paint, so a component that calls
 * this before mount renders the byte-identical default and only switches
 * looks after hydration re-resolves it.
 */
export function resolveFunnelTreatment(
  search?: string | null,
): FunnelTreatment {
  const raw =
    search ?? (typeof window !== "undefined" ? window.location.search : "");
  const look = new URLSearchParams(raw ?? "").get("look");
  return look && VALID_TREATMENTS.has(look)
    ? (look as FunnelTreatment)
    : FUNNEL_TREATMENT;
}
