import { headers } from "next/headers";
import { userAgent } from "next/server";

/**
 * Best-effort mobile hint from the request's User-Agent, read once on the
 * server (mirrors core/i18n/server.ts's detectLocaleServer). Feeds
 * useIsMobile's initial render so a phone's first paint already matches its
 * eventual matchMedia result instead of flashing the desktop shell -- see
 * hooks/use-mobile.ts for the full rationale.
 */
export async function detectIsMobileServer(): Promise<boolean> {
  const { device } = userAgent({ headers: await headers() });
  return device.type === "mobile";
}
