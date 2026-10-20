import { fetch as fetchWithAuth } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type { BrandAbout, BrandKit } from "./types";

export const BRAND_KIT_QUERY_KEY = ["momobot-brand", "kit"] as const;
export const BRAND_ABOUT_QUERY_KEY = ["momobot-brand", "about"] as const;

const BASE = "/api/momobot-brand";

/** Gateway URL for a kit file (icon, video, poster, mascot, font). */
export function brandAssetUrl(path: string): string {
  return `${getBackendBaseURL()}${BASE}/assets/${path}`;
}

async function getJSON<T>(path: string): Promise<T> {
  const response = await fetchWithAuth(`${getBackendBaseURL()}${BASE}${path}`, {
    method: "GET",
  });
  if (!response.ok) throw new Error("MomoBot brand content is not available.");
  return (await response.json()) as T;
}

export const fetchBrandKit = () => getJSON<BrandKit>("/kit");
export const fetchBrandAbout = () => getJSON<BrandAbout>("/about");
