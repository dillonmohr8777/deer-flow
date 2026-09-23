import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";

import LoginPage from "@/app/(auth)/login/page";
import {
  CUT_MS,
  useIntroMotion,
} from "@/components/momentum/momobot/intro-motion";
import { ScrapbookBackdrop } from "@/components/momentum/momobot/scrapbook-backdrop";
import { WavingMomo } from "@/components/momentum/momobot/waving-momo";
import { enUS } from "@/core/i18n/locales/en-US";

rs.mock("next/navigation", () => ({
  useRouter: () => ({ push: () => undefined }),
  useSearchParams: () => new URLSearchParams(),
}));
rs.mock("next-themes", () => ({
  useTheme: () => ({ theme: "light", resolvedTheme: "light" }),
}));
rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: () => ({ isAuthenticated: false }),
}));
rs.mock("@/core/i18n/hooks", () => ({ useI18n: () => ({ t: enUS }) }));

function mockMedia({ reduce }: { reduce: boolean }) {
  window.matchMedia = ((query: string) => ({
    matches: query.includes("reduced-motion") ? reduce : false,
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  })) as unknown as typeof window.matchMedia;
}

function Intro({ cue = 0 }: { cue?: number }) {
  const motion = useIntroMotion();
  return (
    <div data-treatment="paper">
      <ScrapbookBackdrop motion={motion} tone="royal" />
      <WavingMomo live={motion.live} cue={cue} />
    </div>
  );
}

const shownImages = (container: HTMLElement) =>
  [...container.querySelectorAll("[data-collage-src]")].map((img) =>
    img.getAttribute("data-collage-src"),
  );

/** Lets the idle loader mount the collage, then flushes decode promises. */
async function settle(ms: number) {
  await act(async () => {
    await rs.advanceTimersByTimeAsync(ms);
  });
}

beforeEach(() => {
  rs.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  // The collage waits for idle; happy-dom may not have requestIdleCallback.
  Object.defineProperty(window, "requestIdleCallback", {
    configurable: true,
    value: undefined,
  });
});

afterEach(() => {
  cleanup();
  rs.useRealTimers();
});

describe("MomoBot intro", () => {
  it("loads the collage after the page settles and cuts no faster than CUT_MS", async () => {
    mockMedia({ reduce: false });
    const { container } = render(<Intro />);
    expect(shownImages(container)).toEqual([]);
    await settle(250);
    const first = shownImages(container);
    expect(first.length).toBe(8);

    await settle(CUT_MS - 1);
    expect(shownImages(container)).toEqual(first);
    await settle(1);
    const second = shownImages(container);
    expect(second.filter((src, i) => src !== first[i])).toHaveLength(1);
  });

  it("pause control stops the cuts and play resumes them", async () => {
    mockMedia({ reduce: false });
    const { container } = render(<Intro />);
    await settle(250);
    fireEvent.click(screen.getByRole("button", { name: "Pause motion" }));
    const held = shownImages(container);
    await settle(CUT_MS * 5);
    expect(shownImages(container)).toEqual(held);
    expect(
      container.querySelector("[data-live]")?.getAttribute("data-live"),
    ).toBe("false");

    fireEvent.click(screen.getByRole("button", { name: "Play motion" }));
    await settle(CUT_MS);
    expect(shownImages(container)).not.toEqual(held);
  });

  it("reduced motion shows one still collage, a still Momo and no doves", async () => {
    mockMedia({ reduce: true });
    const { container, rerender } = render(<Intro />);
    await settle(250);
    const still = shownImages(container);
    expect(still.length).toBe(8);
    expect(screen.queryByRole("button", { name: /motion/ })).toBeNull();
    expect(container.querySelector("svg")).toBeNull();

    rerender(<Intro cue={1} />);
    await settle(CUT_MS * 5);
    expect(shownImages(container)).toEqual(still);
    expect(
      container.querySelector("[data-frame]")?.getAttribute("data-frame"),
    ).toBe("0");
  });

  it("waves through frames 1, 2 and 3 when motion is allowed", async () => {
    mockMedia({ reduce: false });
    const { container } = render(<Intro />);
    const seen = new Set<string>();
    for (let i = 0; i < 12; i++) {
      seen.add(
        container.querySelector("[data-frame]")!.getAttribute("data-frame")!,
      );
      await settle(160);
    }
    expect([...seen].sort()).toEqual(["0", "1", "2", "3"]);
  });
});

describe("sign in", () => {
  it("names the product in the heading: Sign in to MomoBot", async () => {
    mockMedia({ reduce: true });
    rs.spyOn(globalThis, "fetch").mockImplementation(
      async () =>
        new Response(JSON.stringify({ needs_setup: false, providers: [] })),
    );
    render(<LoginPage />);
    expect(
      screen.getByRole("heading", { level: 1, name: "Sign in to MomoBot" }),
    ).toBeDefined();
    expect(screen.getByText("MomoBot")).toBeDefined();
    expect(screen.getByAltText("Momentum")).toBeDefined();
    await settle(0);
  });
});
