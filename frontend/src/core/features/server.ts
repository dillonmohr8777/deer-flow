import { cookies } from "next/headers";

import { AUTH_REQUEST_TIMEOUT_MS } from "@/core/auth/constants";
import { getGatewayConfig } from "@/core/auth/gateway-config";

import { isDeskEnabled, type FeaturesResponse } from "./api";

/**
 * Server-side read of the Desk flag, for the /workspace redirect. Any
 * failure reads as off, so a client-facing MomoBot always lands on Command
 * Center.
 */
export async function isDeskEnabledOnServer(): Promise<boolean> {
  try {
    const token = (await cookies()).get("access_token")?.value;
    const res = await fetch(
      `${getGatewayConfig().internalGatewayUrl}/api/features`,
      {
        headers: token ? { Cookie: `access_token=${token}` } : undefined,
        cache: "no-store",
        signal: AbortSignal.timeout(AUTH_REQUEST_TIMEOUT_MS),
      },
    );
    if (!res.ok) return false;
    return isDeskEnabled((await res.json()) as FeaturesResponse);
  } catch {
    return false;
  }
}
