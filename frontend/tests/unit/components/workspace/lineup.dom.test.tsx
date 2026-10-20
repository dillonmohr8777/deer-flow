import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, render, screen } from "@testing-library/react";

import {
  AboutContent,
  parseAbout,
} from "@/components/workspace/lineup/about-panel";
import { LineupContent } from "@/components/workspace/lineup/lineup";
import type { BrandKit } from "@/core/momobot-brand";

const mocks = rs.hoisted(() => ({ narrow: false }));

rs.mock("@/hooks/use-mobile", () => ({ useIsMobile: () => mocks.narrow }));

afterEach(() => {
  cleanup();
  mocks.narrow = false;
});

function kit(showPricing: boolean): BrandKit {
  const price = (usd: number | null, shared?: string[]) =>
    showPricing ? { monthly_usd: usd, shared_with: shared } : undefined;
  const agent = (n: number, usd: number | null, shared?: string[]) => ({
    id: `fake-${n}`,
    order: n,
    name: `Fake Agent ${n}`,
    short_name: `F${n}`,
    job: `Does fake job ${n}.`,
    color: "#112233",
    icon: `icons/fake-${n}.svg`,
    icon_alt: `Fake icon ${n}`,
    price: price(usd, shared),
  });
  return {
    name: "Fake kit",
    show_pricing: showPricing,
    brand: { end_card_line: "Fake end card." },
    max_plus: {
      id: "fake-max",
      name: "Fake Max",
      job: "Fake job.",
      tagline: "Fake Max. All fake agents.",
      bundle_line: "Or get them all in one, fake.",
      color: "#112233",
      icon: "icons/fake-max.svg",
      hero_art: "mascot/fake.png",
      includes: [],
      price: price(900),
    },
    agents: [
      agent(2, null, ["fake-3"]),
      agent(1, 10),
      agent(3, 20, ["fake-2"]),
    ],
    videos: {
      first_video: {
        seconds: 5,
        landscape: "videos/a-wide.mp4",
        vertical: "videos/a-tall.mp4",
        poster_landscape: "stills/a-wide.png",
        poster_vertical: "stills/a-tall.png",
      },
      second_video: {
        title: "Second Clip TV",
        seconds: 7,
        landscape: "videos/b-wide.mp4",
        vertical: "videos/b-tall.mp4",
        poster_landscape: "stills/b-wide.png",
        poster_vertical: "stills/b-tall.png",
      },
    },
  };
}

describe("LineupContent", () => {
  it("lists agents in order with name, job, chip and icon alt", () => {
    render(<LineupContent kit={kit(false)} />);
    const names = screen
      .getAllByRole("heading", { level: 3 })
      .map((h) => h.textContent);
    expect(names).toEqual(["Fake Agent 1", "Fake Agent 2", "Fake Agent 3"]);
    expect(screen.getByText("Does fake job 2.")).toBeTruthy();
    expect(screen.getByText("F3")).toBeTruthy();
    expect(screen.getByAltText("Fake icon 1")).toBeTruthy();
  });

  it("uneven layout: entries do not share one span", () => {
    render(<LineupContent kit={kit(false)} />);
    const spans = screen
      .getAllByRole("listitem")
      .map((li) => li.style.getPropertyValue("--span"));
    expect(new Set(spans).size).toBeGreaterThan(1);
  });

  it("shows the flagship tagline and bundle line from the kit", () => {
    render(<LineupContent kit={kit(false)} />);
    expect(screen.getByText("Fake Max. All fake agents.")).toBeTruthy();
    expect(screen.getByText("Or get them all in one, fake.")).toBeTruthy();
    expect(document.querySelector('img[src$="mascot/fake.png"]')).toBeTruthy();
  });

  it("renders no price text at all while pricing is off", () => {
    const { container } = render(<LineupContent kit={kit(false)} />);
    expect(container.textContent).not.toMatch(/\$|Not priced|Shared with/);
  });

  it("prices on: Not priced for null, shared packages named, nothing summed", () => {
    const { container } = render(<LineupContent kit={kit(true)} />);
    const text = container.textContent ?? "";
    expect(text).toContain("Not priced");
    expect(text).not.toContain("$0");
    expect(text).toContain("Shared with Fake Agent 3");
    expect(text).toContain("$10/mo");
    expect(text).toContain("$20/mo");
    expect(text).not.toContain("$30");
  });

  it("renders both videos with controls, posters and no autoplay (landscape)", () => {
    render(<LineupContent kit={kit(false)} />);
    const videos = Array.from(document.querySelectorAll("video"));
    expect(videos).toHaveLength(2);
    for (const v of videos) {
      expect(v.hasAttribute("controls")).toBe(true);
      expect(v.hasAttribute("autoplay")).toBe(false);
      expect(v.getAttribute("preload")).toBe("none");
    }
    expect(videos[0]!.getAttribute("src")).toContain("videos/a-wide.mp4");
    expect(videos[0]!.getAttribute("poster")).toContain("stills/a-wide.png");
  });

  it("labels a video with its kit title, else a title from its key", () => {
    render(<LineupContent kit={kit(false)} />);
    expect(document.querySelector('video[aria-label^="Second Clip TV,"]')).not.toBeNull();
    expect(document.querySelector('video[aria-label^="First video,"]')).not.toBeNull();
  });

  it("uses the vertical cut on narrow screens", () => {
    mocks.narrow = true;
    render(<LineupContent kit={kit(false)} />);
    const first = document.querySelector("video")!;
    expect(first.getAttribute("src")).toContain("videos/a-tall.mp4");
    expect(first.getAttribute("poster")).toContain("stills/a-tall.png");
  });

  it("serves every asset through the gateway route, not a local path", () => {
    render(<LineupContent kit={kit(false)} />);
    const urls = Array.from(document.querySelectorAll("img,video")).map(
      (el) => el.getAttribute("src") ?? "",
    );
    expect(urls.every((u) => u.includes("/api/momobot-brand/assets/"))).toBe(
      true,
    );
  });
});

describe("About panel", () => {
  const md =
    "**Fake lead.** First paragraph.\n\n**Steps.**\n1. One\n2. Two\n\nLast.";

  it("parses paragraphs and numbered lists", () => {
    expect(parseAbout(md)).toEqual([
      { kind: "p", text: "**Fake lead.** First paragraph." },
      { kind: "p", text: "**Steps.**" },
      { kind: "ol", items: ["One", "Two"] },
      { kind: "p", text: "Last." },
    ]);
  });

  it("renders bold and list items", () => {
    render(<AboutContent markdown={md} />);
    expect(screen.getByText("Fake lead.").tagName).toBe("STRONG");
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
  });
});
