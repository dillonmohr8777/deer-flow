"use client";

import { createContext, type ReactNode } from "react";

/**
 * Server-detected mobile hint (see server.ts), or null where no provider is
 * mounted (static export, storybook, tests) -- useIsMobile then falls back
 * to today's "assume desktop" default. See hooks/use-mobile.ts.
 */
export const MobileHintContext = createContext<boolean | null>(null);

export function MobileHintProvider({
  hint,
  children,
}: {
  hint: boolean;
  children: ReactNode;
}) {
  return (
    <MobileHintContext.Provider value={hint}>
      {children}
    </MobileHintContext.Provider>
  );
}
