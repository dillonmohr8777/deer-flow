import { safePluginIcon } from "@/core/mcp/icon";

export type BrandTreatment =
  | "classic"
  | "current"
  | "paper"
  | "space"
  | "future"
  | "retro";

const TREATMENTS: readonly BrandTreatment[] = [
  "classic",
  "current",
  "paper",
  "space",
  "future",
  "retro",
];
export type AppearancePreferences = {
  treatment: BrandTreatment;
  motion: boolean;
  logo: string | null;
  label: string;
};

/** Paper is the product's look; "current" and "classic" stay selectable. */
export const DEFAULT_APPEARANCE: AppearancePreferences = {
  treatment: "paper",
  motion: false,
  logo: null,
  label: "",
};

export function appearanceKey(userId: string) {
  return `momentum:appearance:v1:${encodeURIComponent(userId)}`;
}

/** Browser presentation only. It never changes a workspace or agent record. */
export function parseAppearance(raw: string | null): AppearancePreferences {
  if (!raw || raw.length > 101_000) return { ...DEFAULT_APPEARANCE };
  try {
    const value: unknown = JSON.parse(raw);
    if (!value || typeof value !== "object" || Array.isArray(value))
      return { ...DEFAULT_APPEARANCE };
    const record = value as Record<string, unknown>;
    return {
      // A saved choice always wins; only a missing or unknown one gets the default.
      treatment: TREATMENTS.includes(record.treatment as BrandTreatment)
        ? (record.treatment as BrandTreatment)
        : DEFAULT_APPEARANCE.treatment,
      motion: record.motion === true,
      logo: safePluginIcon(record.logo) ?? null,
      label:
        typeof record.label === "string"
          ? [...record.label.replace(/[\u0000-\u001f\u007f]/g, "").trim()]
              .slice(0, 40)
              .join("")
          : "",
    };
  } catch {
    return { ...DEFAULT_APPEARANCE };
  }
}

export function brandMotionAllowed({
  motion,
  reducedMotion,
  visible,
  inView,
}: {
  motion: boolean;
  reducedMotion: boolean;
  visible: boolean;
  inView: boolean;
}) {
  return motion && !reducedMotion && visible && inView;
}
