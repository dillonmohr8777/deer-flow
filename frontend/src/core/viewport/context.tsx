"use client";

import { createContext, type ReactNode } from "react";

/**
 * Server-detected mobile hint (see server.ts). It's null where no provider is
 * mounted, and useIsMobile then assumes desktop.
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
