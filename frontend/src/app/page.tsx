import { MomentumLanding } from "@/components/momentum/landing/momentum-landing";
import { COMIC_BOOT_SCRIPT } from "@/components/momentum/momobot/comic-data";

/*
 * Momentum serves its own front door here instead of the upstream open-source
 * landing page. The upstream components remain untouched under
 * src/components/landing/** so pulls from origin/main stay conflict-free;
 * this file is the single seam.
 *
 * The inline script decides before first paint whether the comic intro plays
 * (once per session, never under reduced motion), so the settled hero never
 * flashes before it. It only sets html[data-comic-intro]; the landing claims
 * the decision after hydration.
 */
export default function LandingPage() {
  return (
    <>
      <script dangerouslySetInnerHTML={{ __html: COMIC_BOOT_SCRIPT }} />
      <MomentumLanding />
    </>
  );
}
