import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, render, screen, within } from "@testing-library/react";

import { MomentumLanding } from "@/components/momentum/landing/momentum-landing";
import { BRAIN_FLAT } from "@/components/workspace/command-center/momo-avatar";

rs.mock("next/navigation", () => ({
  useRouter: () => ({ push: () => undefined }),
  useSearchParams: () => new URLSearchParams(),
}));

beforeEach(() => {
  window.matchMedia = ((query: string) => ({
    matches: query.includes("reduced-motion"),
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  })) as unknown as typeof window.matchMedia;
  rs.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(
    () => undefined,
  );
});

afterEach(() => {
  cleanup();
  rs.restoreAllMocks();
});

describe("landing team sheet (d7)", () => {
  it("shows the lead first, then the five specialists the Agents card names", () => {
    render(<MomentumLanding />);

    const team = screen.getByRole("region", { name: "Your team" });
    const members = within(team).getAllByRole("listitem");
    expect(members.map((m) => m.textContent)).toEqual([
      "Lead",
      "Research",
      "Growth",
      "Revenue",
      "Client success",
      "Release review",
    ]);

    // Every specialist on the sheet is named in the Agents card copy, so
    // the illustration and the words describe the same team.
    const agents = screen.getByText("Agents").closest("li");
    for (const name of ["research", "growth", "revenue", "client success"]) {
      expect(agents?.textContent?.toLowerCase()).toContain(name);
    }
  });

  it("draws the roster art as decoration, with the name as the text", () => {
    render(<MomentumLanding />);

    const team = screen.getByRole("region", { name: "Your team" });
    const art = [...team.querySelectorAll("img")];
    expect(art).toHaveLength(6);
    for (const img of art) {
      expect(img.getAttribute("alt")).toBe("");
    }
    // The lead is Dillon Brain, the art the Command Center draws for the
    // lead, not the unused generic lead Momo.
    expect(art[0]!.getAttribute("src")).toBe(BRAIN_FLAT);
    for (const img of art.slice(1)) {
      expect(img.getAttribute("src")).toMatch(
        /^\/momentum\/momos\/[a-z-]+\.svg$/,
      );
    }
  });

  it("rests unpinned: a pin means work in progress", () => {
    render(<MomentumLanding />);

    const team = screen.getByRole("region", { name: "Your team" });
    expect(team.classList.contains("pinned")).toBe(false);
    expect(team.querySelector(".pinned")).toBeNull();
  });
});
