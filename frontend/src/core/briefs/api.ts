import { fetch as fetchWithAuth } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type { TodayBrief } from "./types";

/**
 * Only call this when the visitor is already known to be signed in (the Daily
 * page is public). `fetchWithAuth` redirects to /login on 401, which is right
 * for the authenticated workspace but would hijack an anonymous reader's visit
 * to a public page, so callers gate on a server-resolved `signedIn` flag first.
 */
export function fetchTodayBrief() {
  return fetchWithAuth(`${getBackendBaseURL()}/api/briefs/today`, {
    method: "GET",
  }).then((response) => {
    if (!response.ok) {
      throw new Error(`Brief request failed (${response.status})`);
    }
    return response.json() as Promise<TodayBrief>;
  });
}
