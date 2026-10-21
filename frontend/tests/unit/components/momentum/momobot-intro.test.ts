import { describe, expect, it } from "@rstest/core";

import { LANDING_SCRIM_ALPHA } from "@/components/momentum/momobot/intro-motion";

function luminance(rgb: number[]) {
  const [r, g, b] = rgb.map((v) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r! + 0.7152 * g! + 0.0722 * b!;
}

function contrast(a: number[], b: number[]) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi! + 0.05) / (lo! + 0.05);
}

const hex = (value: string) =>
  [1, 3, 5].map((i) => parseInt(value.slice(i, i + 2), 16));

// The landing hero now sits on the comic wall (its scrim is pinned in
// comic-data.test.ts); this pins ScrapbookBackdrop's cream collage scrim.
describe("MomoBot intro motion contract", () => {
  it("keeps copy at 4.5:1 over any frame of the cream collage", () => {
    const cream = hex("#f2ede3"); // --paper-cream
    for (const ink of ["#101e3f", "#3a4a6b"]) {
      // --paper-ink, --paper-ink-muted
      for (const under of [
        [0, 0, 0],
        [255, 255, 255],
        [27, 75, 158],
      ]) {
        const surface = cream.map(
          (c, i) =>
            LANDING_SCRIM_ALPHA * c + (1 - LANDING_SCRIM_ALPHA) * under[i]!,
        );
        expect(contrast(hex(ink), surface)).toBeGreaterThanOrEqual(4.5);
      }
    }
  });
});
