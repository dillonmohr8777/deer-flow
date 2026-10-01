import { readFileSync } from "node:fs";
import { join } from "node:path";

import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

import LoginPage from "@/app/(auth)/login/page";
import InvitePage from "@/app/invite/page";
import { MomentumLanding } from "@/components/momentum/landing/momentum-landing";
import { enUS } from "@/core/i18n/locales/en-US";

// DESIGN.md: a brass pin means something is working right now. Paper at
// rest sits in photo corners (paper.css's .paper-corners) instead, and a
// pin goes in only while a request runs.

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

beforeEach(() => {
  window.matchMedia = ((query: string) => ({
    matches: query.includes("reduced-motion"),
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  })) as unknown as typeof window.matchMedia;
  rs.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
  rs.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(
    () => undefined,
  );
});

afterEach(() => {
  cleanup();
  rs.restoreAllMocks();
  window.history.replaceState(null, "", "/");
});

const never = () => new Promise<Response>(() => undefined);

describe("pins mean running", () => {
  it("landing capability cards rest in photo corners, never pinned", () => {
    const { container } = render(<MomentumLanding />);
    const cards = screen.getByText("Agents").closest("ul")!.children;
    expect(cards.length).toBe(4);
    for (const card of Array.from(cards)) {
      expect(card.classList.contains("pinned")).toBe(false);
      const corners = card.querySelector(".paper-corners");
      expect(corners?.getAttribute("aria-hidden")).toBe("true");
    }
    expect(container.querySelector(".pinned")).toBeNull();
  });

  it("the invite is pinned only while it is being accepted", async () => {
    window.history.replaceState(null, "", "/invite#token=abc");
    rs.spyOn(globalThis, "fetch").mockImplementation(async (input) =>
      (input as string).endsWith("/inspect")
        ? new Response(
            JSON.stringify({
              email: "person@example.com",
              workspace_name: "Team",
              expires_at: "2026-10-01T00:00:00Z",
              requires_login: true,
            }),
          )
        : never(),
    );
    const { container } = render(<InvitePage />);
    const password = await screen.findByLabelText("Current password");
    expect(container.querySelector(".pinned")).toBeNull();
    expect(container.querySelector(".paper-corners")).not.toBeNull();

    fireEvent.change(password, { target: { value: "valid123" } });
    fireEvent.submit(
      screen.getByRole("button", { name: "Accept invite" }).closest("form")!,
    );
    await screen.findByRole("button", { name: "Accepting…" });
    expect(container.querySelector(".pinned")).not.toBeNull();
  });

  it("the sign-in sheet is pinned only while signing in", async () => {
    rs.spyOn(globalThis, "fetch").mockImplementation(async (input) =>
      (input as string).includes("/login/local")
        ? never()
        : new Response(JSON.stringify({ needs_setup: false, providers: [] })),
    );
    const { container } = render(<LoginPage />);
    expect(container.querySelector(".pinned")).toBeNull();
    expect(container.querySelector(".paper-corners")).not.toBeNull();

    const form = container.querySelector("form")!;
    fireEvent.change(form.querySelector('input[type="email"]')!, {
      target: { value: "person@example.com" },
    });
    fireEvent.change(form.querySelector('input[type="password"]')!, {
      target: { value: "valid-password" },
    });
    fireEvent.submit(form);
    await waitFor(() =>
      expect(container.querySelector(".pinned")).not.toBeNull(),
    );
  });

  it("photo corners are drawn from paper tokens only", () => {
    const css = readFileSync(
      join(process.cwd(), "src/styles/paper.css"),
      "utf-8",
    );
    const rule = /\.paper-corners \{([^}]*)\}/.exec(css)?.[1] ?? "";
    expect(rule).toContain("var(--paper-kraft)");
    expect(rule).not.toMatch(/#[0-9a-f]{3,8}\b/i);
    // Decoration is dropped under forced-colors, like the pin and grain.
    const forced = css.slice(css.indexOf("@media (forced-colors: active)"));
    expect(forced).toContain(".paper-corners");
  });
});
