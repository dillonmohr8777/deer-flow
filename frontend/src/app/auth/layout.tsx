import { type ReactNode } from "react";

// The SSO callback runs after the provider has already set the session
// cookie. Under (auth)/layout.tsx it was bounced to /workspace like every
// signed-in visitor, so ?next= (for example /invite, to finish accepting an
// invitation) was always dropped. It lives outside that group on purpose;
// the page itself checks the session and follows a validated next path.
export const dynamic = "force-dynamic";

export default function AuthCallbackLayout({
  children,
}: {
  children: ReactNode;
}) {
  return children;
}
