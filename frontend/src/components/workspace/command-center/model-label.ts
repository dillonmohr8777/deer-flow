/**
 * Turn an internal routing slug into something a client can be shown.
 *
 * Agent cards were printing the raw slug — `openrouter-opus-5`,
 * `openrouter-muse-spark-contributor`, `openrouter-fable-5.1`. Two problems:
 * it is provider plumbing leaking into a product surface, and the
 * `-contributor` suffix breaks the standing rule that the Contributor tier is
 * never advertised publicly. Only the model name may be shown.
 *
 * Deliberately a pure string function with no lookup table of every slug: new
 * models appear constantly, and an unknown slug must still render as something
 * presentable rather than falling back to the raw routing string.
 */

/** Routing prefixes that identify *where* a model is served, not which model. */
const PROVIDER_PREFIXES = ["openrouter-", "vercel-", "ollama-", "gateway-"];

/**
 * Commercial tier markers. These must never reach a product surface, per the
 * standing rule about Contributor tier. Stripped from the end of the slug.
 */
const TIER_SUFFIXES = ["-contributor", "-batch", ":batch", "-preview", "-beta"];

/** The same markers as whole words, for display names and a final guard. */
const TIER_WORDS = /\b(contributor|batch|preview|beta)\b/gi;

/** Families whose display name is not simply the title-cased slug. */
const FAMILIES: ReadonlyArray<readonly [RegExp, string]> = [
  [/^claude-?/, "Claude "],
  [/^(opus|sonnet|haiku|fable)\b/, "Claude $1 "],
  [/^muse-spark(-1\.3)?$/, "Muse Spark 1.3"],
  [/^gpt-/, "GPT-"],
  [/^deepseek-/, "DeepSeek "],
];

function withoutTierWords(value: string): string {
  return value.replace(TIER_WORDS, " ").replace(/\s+/g, " ").trim();
}

function titleCaseWords(value: string): string {
  return value
    .split(/[-_\s]+/)
    .filter(Boolean)
    .map((word) =>
      /^\d/.test(word) ? word : word.charAt(0).toUpperCase() + word.slice(1),
    )
    .join(" ");
}

/**
 * Format a model slug for display.
 *
 * @param slug  Internal routing slug, or "inherit".
 * @returns A presentable model name. Never returns a tier marker.
 */
export function formatModelLabel(slug: string | null | undefined): string {
  if (!slug) return "";

  let value = slug.trim().toLowerCase();
  if (value === "inherit") return "Lead model";

  // A namespace ("meta/", "google/") names the vendor, not the model. Taking
  // the last segment also recovers the model from the doubled IDs the usage
  // ledger currently records ("meta/x-contributormeta/x-contributor").
  value = value.slice(value.lastIndexOf("/") + 1);

  for (const prefix of PROVIDER_PREFIXES) {
    if (value.startsWith(prefix)) {
      value = value.slice(prefix.length);
      break;
    }
  }

  // Strip repeatedly: a slug can carry more than one marker.
  let stripped = true;
  while (stripped) {
    stripped = false;
    for (const suffix of TIER_SUFFIXES) {
      if (value.endsWith(suffix)) {
        value = value.slice(0, -suffix.length);
        stripped = true;
      }
    }
  }

  if (!value) return "";

  if (value.startsWith("muse-spark")) return "Muse Spark 1.3";

  for (const [pattern, replacement] of FAMILIES) {
    if (pattern.test(value)) {
      const named = value.replace(pattern, replacement).trim();
      return withoutTierWords(titleCaseWords(named).replace(/\bGpt\b/g, "GPT"));
    }
  }

  return withoutTierWords(titleCaseWords(value));
}

/**
 * The name a person configured for a model, when the slug is one of the
 * workspace's configured models, minus the provider in parentheses
 * ("(OpenRouter)") and any tier word. Configured names carry the tier word
 * today ("Muse Spark 1.3 Contributor (OpenRouter)"), so they are cleaned, not
 * trusted. Anything the model list does not know, such as the provider model
 * IDs in usage rows, falls back to formatModelLabel.
 */
export function modelDisplayName(
  slug: string | null | undefined,
  models: ReadonlyArray<{ name: string; display_name?: string | null }> = [],
): string {
  const configured = slug
    ? models.find((model) => model.name === slug)?.display_name
    : null;
  const cleaned = withoutTierWords(
    (configured ?? "").replace(/\s*\([^)]*\)\s*$/, ""),
  );
  return cleaned || formatModelLabel(slug);
}
