import { safePluginIcon } from "@/core/mcp/icon";

export type BrandTreatment = "classic" | "current" | "paper";
export type AppearancePreferences = {
  treatment: BrandTreatment;
  motion: boolean;
  logo: string | null;
  label: string;
  followWorkspaceStyle: boolean;
};

export const DEFAULT_APPEARANCE: AppearancePreferences = {
  treatment: "current",
  motion: false,
  logo: null,
  label: "",
  followWorkspaceStyle: true,
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
      treatment:
        record.treatment === "classic" || record.treatment === "paper"
          ? record.treatment
          : "current",
      motion: record.motion === true,
      followWorkspaceStyle:
        typeof record.followWorkspaceStyle === "boolean"
          ? record.followWorkspaceStyle
          : !["classic", "current", "paper"].includes(String(record.treatment)),
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
