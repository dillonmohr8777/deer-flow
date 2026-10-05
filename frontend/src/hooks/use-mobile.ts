import * as React from "react";

import { MobileHintContext } from "@/core/viewport/context";

const MOBILE_BREAKPOINT = 768;

function query(breakpoint: number) {
  return `(max-width: ${breakpoint - 1}px)`;
}

/**
 * The server snapshot comes from a User-Agent hint (core/viewport), so a
 * phone's first paint is already the mobile shell instead of flashing the
 * desktop one. With no provider mounted (static export, tests) it's desktop.
 * `breakpoint` is the first desktop width: 768 for the shell, 640 where a
 * rule follows Tailwind's `sm` (phone slips, DESIGN.md Phones).
 */
export function useIsMobile(breakpoint = MOBILE_BREAKPOINT) {
  const hint = React.useContext(MobileHintContext);
  const subscribe = React.useCallback(
    (callback: () => void) => {
      const mql = window.matchMedia(query(breakpoint));
      mql.addEventListener("change", callback);
      return () => mql.removeEventListener("change", callback);
    },
    [breakpoint],
  );
  const getSnapshot = React.useCallback(
    () => window.matchMedia(query(breakpoint)).matches,
    [breakpoint],
  );
  const getServerSnapshot = React.useCallback(() => hint ?? false, [hint]);
  return React.useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
