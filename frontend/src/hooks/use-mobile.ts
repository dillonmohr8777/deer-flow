import * as React from "react";

import { MobileHintContext } from "@/core/viewport/context";

const MOBILE_BREAKPOINT = 768;
const MOBILE_QUERY = `(max-width: ${MOBILE_BREAKPOINT - 1}px)`;

function subscribe(callback: () => void) {
  const mql = window.matchMedia(MOBILE_QUERY);
  mql.addEventListener("change", callback);
  return () => mql.removeEventListener("change", callback);
}

function getSnapshot() {
  return window.matchMedia(MOBILE_QUERY).matches;
}

/**
 * The server snapshot comes from a User-Agent hint (core/viewport), so a
 * phone's first paint is already the mobile shell instead of flashing the
 * desktop one. With no provider mounted (static export, tests) it's desktop.
 */
export function useIsMobile() {
  const hint = React.useContext(MobileHintContext);
  const getServerSnapshot = React.useCallback(() => hint ?? false, [hint]);
  return React.useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
