import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, waitFor } from "@testing-library/react";

import { DailyFrontPage } from "@/components/momentum/daily/front-page";
import { StaffPortrait } from "@/components/momentum/daily/staff-box";
import { parseArticle } from "@/core/momo-daily";

rs.mock("next/navigation", () => ({
  useRouter: () => ({ push: () => undefined, prefetch: () => undefined }),
}));

const ARTICLE = parseArticle({
  title: "How should agents hand work back?",
  dek: "Knowing when to stop.",
  slug: "hand-work-back",
  date: "2026-09-22",
  author: { name: "Dillon Mohr" },
  summary: "At the moment an action becomes hard to undo.",
  section: "Safety",
  hero: {
    src: "/momentum/momos-living/verifier/flat.webp",
    alt: "Verifier Momo",
  },
  status: "draft",
  body: [{ heading: "When?", paragraphs: ["Before a send."] }],
});

/** Desktop with a fine pointer; `reduce` toggles prefers-reduced-motion. */
function mockMedia({ reduce }: { reduce: boolean }) {
  window.matchMedia = ((query: string) => ({
    matches: query.includes("reduced-motion") ? reduce : true,
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  })) as unknown as typeof window.matchMedia;
}

afterEach(cleanup);

describe("The Momo Daily front page", () => {
  it("plays 3D paper only when motion is allowed", async () => {
    mockMedia({ reduce: false });
    const { container } = render(
      <DailyFrontPage
        articles={[ARTICLE]}
        editionDate="Tuesday, September 22, 2026"
      />,
    );
    await waitFor(() =>
      expect(container.querySelector('[data-motion="on"]')).toBeTruthy(),
    );
    expect(container.querySelector("[data-depth]")).toBeTruthy();
  });

  it("disables all 3D motion under prefers-reduced-motion", async () => {
    mockMedia({ reduce: true });
    const { container } = render(
      <DailyFrontPage
        articles={[ARTICLE]}
        editionDate="Tuesday, September 22, 2026"
      />,
    );
    // Let the mount effect settle, then assert it stayed flat.
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(container.querySelector('[data-motion="off"]')).toBeTruthy();
    expect(container.querySelector('[data-motion="on"]')).toBeNull();
    // Every Momo renders as a single flat image: no layered stage.
    expect(container.querySelector("[data-depth]")).toBeNull();
  });

  it("stamps drafts", () => {
    mockMedia({ reduce: true });
    const { getAllByText } = render(
      <DailyFrontPage
        articles={[ARTICLE]}
        editionDate="Tuesday, September 22, 2026"
      />,
    );
    expect(getAllByText("Draft").length).toBeGreaterThan(0);
  });
});

describe("StaffPortrait", () => {
  it("falls back when the portrait had already failed before hydration", () => {
    // happy-dom reports an unfetched <img> as complete with no pixels: the
    // same state a browser leaves a 404 in before React attaches onError.
    const { container, getByRole } = render(
      <StaffPortrait slug="nobody" name="Nobody Here" />,
    );
    expect(container.querySelector('img[data-portrait="photo"]')).toBeNull();
    expect(
      getByRole("img", { name: "Engraving placeholder for Nobody Here" }),
    ).toBeTruthy();
  });

  it("falls back to the engraved Momo when the portrait fails to load", () => {
    // Still loading on mount (the normal lazy case), then the request 404s.
    const complete = rs
      .spyOn(HTMLImageElement.prototype, "complete", "get")
      .mockReturnValue(false);
    const { container, getByRole } = render(
      <StaffPortrait slug="nobody" name="Nobody Here" />,
    );
    const img = container.querySelector('img[data-portrait="photo"]');
    expect(img?.getAttribute("src")).toBe("/momentum/daily/people/nobody.webp");

    fireEvent.error(img!);

    expect(container.querySelector('img[data-portrait="photo"]')).toBeNull();
    expect(
      getByRole("img", { name: "Engraving placeholder for Nobody Here" }),
    ).toBeTruthy();
    complete.mockRestore();
  });
});
