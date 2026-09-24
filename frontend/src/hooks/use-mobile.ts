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
 * getServerSnapshot always returning false meant a phone's first paint (SSR,
 * then the matching first client render before hydration corrects it) was
 * always the desktop shell -- useSyncExternalStore's post-hydration
 * correction runs on a passive-effect timing, so the wrong shell paints for
 * a frame before flipping. A pure CSS-first breakpoint would need every
 * isMobile consumer that renders a *different* tree (not just different
 * classes) to carry its own media-query guard, which is the wider, riskier
 * change (ui/sidebar.tsx already does this for its desktop branch via
 * `hidden md:block`; chat-box.tsx's ResizablePanelGroup-vs-Sheet branch does
 * not, and is the one place the flash is actually visible today).
 * Reading a client hint is the smaller, one-place fix: MobileHintProvider
 * (see core/viewport) seeds this from the request's User-Agent via Next's
 * own `userAgent()` helper, server-side, once, near the root. It is a
 * heuristic, not a live viewport reading, so it can be wrong (a desktop
 * browser resized narrow reads as "desktop" until matchMedia's listener
 * fires) -- but it removes the flash for the overwhelming common case, a
 * phone's own browser, whose UA reliably self-identifies. No provider
 * mounted (static export, tests, Storybook) falls back to today's false.
 */
export function useIsMobile() {
  const hint = React.useContext(MobileHintContext);
  const getServerSnapshot = React.useCallback(() => hint ?? false, [hint]);
  return React.useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
