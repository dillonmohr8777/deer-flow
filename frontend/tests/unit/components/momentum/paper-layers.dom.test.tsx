import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, render } from "@testing-library/react";

import { PaperLayers } from "@/components/momentum/paper-layers";

const appearance = rs.hoisted(() => ({
  value: {
    preferences: {
      treatment: "paper" as const,
      motion: true,
      logo: null,
      label: "",
    },
    reducedMotion: false,
    visible: true,
  },
}));

rs.mock("@/components/workspace/command-center/appearance-provider", () => ({
  useWorkspaceAppearance: () => appearance.value,
}));

function motion(allowed: { motion?: boolean; reducedMotion?: boolean }) {
  appearance.value = {
    ...appearance.value,
    preferences: {
      ...appearance.value.preferences,
      motion: allowed.motion ?? true,
    },
    reducedMotion: allowed.reducedMotion ?? false,
  };
}

const LAYERS = [
  "/momentum/brain/kraft.webp",
  "/momentum/brain/body.webp",
  "/momentum/brain/folds.webp",
];
const FLAT = "/momentum/brain/flat.webp";

beforeEach(() => motion({}));
afterEach(cleanup);

describe("PaperLayers", () => {
  it("renders only the flattened image below 40px, no stage", () => {
    const { container } = render(
      <PaperLayers
        layers={LAYERS}
        flatSrc={FLAT}
        size={32}
        alt="Dillon Brain"
      />,
    );
    const imgs = container.querySelectorAll("img");
    expect(imgs).toHaveLength(1);
    expect(imgs[0]?.getAttribute("src")).toBe(FLAT);
    expect(container.querySelector("[data-depth]")).toBeNull();
  });

  it("holds fully static under reduced motion or the app motion switch off, even at hero size", () => {
    for (const setting of [
      { reducedMotion: true },
      { motion: false },
    ] as const) {
      motion(setting);
      const { container, unmount } = render(
        <PaperLayers
          layers={LAYERS}
          flatSrc={FLAT}
          size={160}
          state="working"
          alt="Dillon Brain"
        />,
      );
      const imgs = container.querySelectorAll("img");
      expect(imgs).toHaveLength(1);
      expect(imgs[0]?.getAttribute("src")).toBe(FLAT);
      unmount();
    }
  });

  it("applies the breathe class only while state is working", () => {
    const { container: idle } = render(
      <PaperLayers
        layers={LAYERS}
        flatSrc={FLAT}
        size={160}
        state="idle"
        alt="Dillon Brain"
      />,
    );
    expect(idle.querySelector('[data-state="idle"]')).toBeTruthy();
    expect(idle.querySelector('[data-state="working"]')).toBeNull();

    const { container: working } = render(
      <PaperLayers
        layers={LAYERS}
        flatSrc={FLAT}
        size={160}
        state="working"
        alt="Dillon Brain"
      />,
    );
    expect(working.querySelector('[data-state="working"]')).toBeTruthy();
  });

  it("gives alt only to the top layer; the rest stay aria-hidden", () => {
    const { container } = render(
      <PaperLayers
        layers={LAYERS}
        flatSrc={FLAT}
        size={160}
        alt="Dillon Brain"
      />,
    );
    const imgs = [...container.querySelectorAll("img[data-depth]")];
    expect(imgs).toHaveLength(3);
    const [kraft, body, folds] = imgs;
    expect(kraft?.getAttribute("alt")).toBe("");
    expect(kraft?.getAttribute("aria-hidden")).toBe("true");
    expect(body?.getAttribute("alt")).toBe("");
    expect(body?.getAttribute("aria-hidden")).toBe("true");
    expect(folds?.getAttribute("alt")).toBe("Dillon Brain");
    expect(folds?.getAttribute("aria-hidden")).toBeNull();
  });
});
