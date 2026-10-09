export const WORKSPACE_MAIN_ID = "workspace-main";

/**
 * The persistent React-owned div `WorkspaceContent` always renders as the
 * sole child of `#workspace-main`, holding the connectivity banners and the
 * routed page content. `RetroResolve` targets this id to apply its
 * pixelation filter as a plain style property, never by moving this node's
 * children in and out of a wrapper it builds itself — see the "why a
 * persistent target" note in retro-resolve.tsx.
 */
export const WORKSPACE_MAIN_CONTENT_ID = "workspace-main-content";

/**
 * First tab stop in the workspace. Without it a keyboard user crosses every
 * sidebar link and each recent chat's "More" button (30+ stops) before
 * reaching the page they opened.
 */
export function SkipToContent() {
  return (
    <a
      href={`#${WORKSPACE_MAIN_ID}`}
      className="bg-background text-foreground sr-only z-50 rounded-md px-4 py-2 text-sm font-semibold shadow-md focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:outline-2 focus:outline-offset-2 focus:outline-[#003da5]"
    >
      Skip to content
    </a>
  );
}
