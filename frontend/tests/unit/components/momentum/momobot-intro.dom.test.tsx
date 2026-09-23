import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";

import LoginPage from "@/app/(auth)/login/page";
import { useIntroMotion } from "@/components/momentum/momobot/intro-motion";
import { ScrapbookBackdrop } from "@/components/momentum/momobot/scrapbook-backdrop";
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

function Intro() {
  const motion = useIntroMotion();
  return (
    <div data-treatment="paper">
      <ScrapbookBackdrop motion={motion} tone="royal" />
    </div>
  );
}

let play: ReturnType<typeof rs.spyOn>;
let pause: ReturnType<typeof rs.spyOn>;
/** Lets the idle loader mount the collage, then flushes decode promises. */
async function settle(ms: number) {
  await act(async () => {
    await rs.advanceTimersByTimeAsync(ms);
  });
}

beforeEach(() => {
  play = rs
    .spyOn(HTMLMediaElement.prototype, "play")
    .mockResolvedValue(undefined);
  pause = rs
    .spyOn(HTMLMediaElement.prototype, "pause")
    .mockImplementation(() => undefined);
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
  rs.restoreAllMocks();
});

describe("MomoBot intro", () => {
  it("plays the collage film only after the page settles", async () => {
    mockMedia({ reduce: false });
    const { container } = render(<Intro />);
    const film = container.querySelector("video")!;
    expect(film.getAttribute("poster")).toBe(
      "/momentum/films/momo-collage.webp",
    );
    expect(film.getAttribute("preload")).toBe("none");
    expect(play).not.toHaveBeenCalled();
    await settle(250);
    expect(play).toHaveBeenCalledTimes(1);
  });

  it("pause control holds the film and play resumes it", async () => {
    mockMedia({ reduce: false });
    const { container } = render(<Intro />);
    await settle(250);
    fireEvent.click(screen.getByRole("button", { name: "Pause motion" }));
    expect(pause).toHaveBeenCalled();
    expect(
      container.querySelector("[data-live]")?.getAttribute("data-live"),
    ).toBe("false");

    fireEvent.click(screen.getByRole("button", { name: "Play motion" }));
    expect(play).toHaveBeenCalledTimes(2);
  });

  it("reduced motion shows a still collage and no doves", async () => {
    mockMedia({ reduce: true });
    const { container } = render(<Intro />);
    await settle(250);
    expect(container.querySelector("video")?.getAttribute("poster")).toBe(
      "/momentum/films/momo-collage.webp",
    );
    expect(play).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: /motion/ })).toBeNull();
    expect(container.querySelector("svg")).toBeNull();
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
