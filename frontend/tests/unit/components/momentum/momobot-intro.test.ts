import { describe, expect, it } from "@rstest/core";

import {
  collageFrame,
  CUT_MS,
  LANDING_SCRIM_ALPHA,
  MIN_CUT_MS,
  waveTimeline,
} from "@/components/momentum/momobot/intro-motion";
import { COLLAGE_IMAGES } from "@/components/momentum/momobot/scrapbook-backdrop";

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

describe("MomoBot intro motion contract", () => {
  it("never cuts the collage faster than once a second", () => {
    expect(MIN_CUT_MS).toBe(1000);
    expect(CUT_MS).toBeGreaterThanOrEqual(MIN_CUT_MS);
  });

  it("changes one clipping per cut and never shows an image twice at once", () => {
    const slots = 8;
    for (let tick = 0; tick < 200; tick++) {
      const now = collageFrame(tick, slots, COLLAGE_IMAGES.length);
      const next = collageFrame(tick + 1, slots, COLLAGE_IMAGES.length);
      expect(new Set(now).size).toBe(slots);
      expect(now.filter((image, slot) => image !== next[slot])).toHaveLength(1);
    }
  });

  it("waves 0,1,0,2,0,3 at about 160ms a frame, pauses, and rests on 0", () => {
    const steps = waveTimeline();
    expect(steps.slice(0, 6).map((s) => s.frame)).toEqual([0, 1, 0, 2, 0, 3]);
    expect(steps.slice(0, 6).every((s) => s.ms === 160)).toBe(true);
    expect(steps[6]!.frame).toBe(0);
    expect(steps[6]!.ms).toBeGreaterThan(160);
    expect(steps.at(-1)!.frame).toBe(0);
  });

  it("keeps landing hero copy at 4.5:1 over any collage image", () => {
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

  it("ships 30 to 40 collage images", () => {
    expect(COLLAGE_IMAGES.length).toBeGreaterThanOrEqual(30);
    expect(COLLAGE_IMAGES.length).toBeLessThanOrEqual(40);
  });
});
