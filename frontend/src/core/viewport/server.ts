import { headers } from "next/headers";
import { userAgent } from "next/server";

/**
 * Best-effort mobile hint from the request's User-Agent, read on the server
 * like detectLocaleServer. It seeds useIsMobile's first render.
 */
export async function detectIsMobileServer(): Promise<boolean> {
  const { device } = userAgent({ headers: await headers() });
  return device.type === "mobile";
}
