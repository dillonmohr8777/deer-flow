import { MomentumLanding } from "@/components/momentum/landing/momentum-landing";

/*
 * Momentum serves its own front door here instead of the upstream open-source
 * landing page. The upstream components remain untouched under
 * src/components/landing/** so pulls from origin/main stay conflict-free;
 * this file is the single seam.
 */
export default function LandingPage() {
  return <MomentumLanding />;
}
