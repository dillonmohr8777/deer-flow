import { afterEach, describe, expect, it, rs } from "@rstest/core";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

import { WelcomeClientsCard } from "@/components/workspace/welcome-clients-card";
import { AuthProvider } from "@/core/auth/AuthProvider";
import type { User } from "@/core/auth/types";
import { updateLocalSettings } from "@/core/settings/store";
import {
  buildComposerDraftKey,
  getSessionComposerDraftStorage,
  readComposerDraft,
} from "@/core/threads/composer-draft";

const pushMock = rs.fn();
rs.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock, replace: rs.fn(), refresh: rs.fn() }),
  usePathname: () => "/workspace",
}));

rs.mock("@/core/static-mode", () => ({
  isStaticWebsiteOnly: () => false,
}));

rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    locale: "en-US",
    t: {
      workspace: {
        welcomeClientsCardTitle: "Set up my clients",
        welcomeClientsCardBody: "Draft a profile and set each one up.",
        welcomeClientsCardCta: "Get started",
        welcomeClientsCardDismiss: "Dismiss",
      },
    },
    changeLocale: rs.fn(),
  }),
}));

const USER: User = {
  id: "user-1",
  email: "beth@example.com",
  system_role: "user",
  needs_setup: false,
};

function resetLocalSettings() {
  updateLocalSettings("context", {
    experience_mode: undefined,
    welcomeClientsCardDismissed: undefined,
  });
}

afterEach(() => {
  pushMock.mockClear();
  rs.restoreAllMocks();
  cleanup();
  resetLocalSettings();
  window.sessionStorage.clear();
});

/** Records every /api/v1/auth/preferences call; other fetches 404 harmlessly. */
function installPreferencesFetch(
  getResponse: () => Record<string, unknown>,
): Array<{ method: string; body: unknown }> {
  const calls: Array<{ method: string; body: unknown }> = [];
  rs.spyOn(globalThis, "fetch").mockImplementation(
    (input: RequestInfo | URL, init?: RequestInit) => {
      const url =
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.toString()
            : input.url;
      if (!url.includes("/api/v1/auth/preferences")) {
        return Promise.resolve(new Response("not found", { status: 404 }));
      }
      const method = (init?.method ?? "GET").toUpperCase();
      calls.push({
        method,
        body: init?.body ? JSON.parse(init.body as string) : undefined,
      });
      return Promise.resolve(
        new Response(JSON.stringify(getResponse()), {
          status: method === "PATCH" ? 204 : 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    },
  );
  return calls;
}

function renderCard(user: User | null) {
  return render(
    <AuthProvider initialUser={user}>
      <WelcomeClientsCard />
    </AuthProvider>,
  );
}

describe("WelcomeClientsCard", () => {
  it("renders nothing before the experience-mode chooser has resolved", async () => {
    installPreferencesFetch(() => ({ welcome_clients_dismissed: false }));
    renderCard(USER);

    // Give any pending effects a tick, then confirm it never appears.
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(
      screen.queryByRole("region", { name: "Set up my clients" }),
    ).toBeNull();
  });

  it("renders once the experience mode is set and the server preference is not dismissed", async () => {
    updateLocalSettings("context", { experience_mode: "easy" });
    installPreferencesFetch(() => ({ welcome_clients_dismissed: false }));
    renderCard(USER);

    // findByRole itself throws/rejects if the card never appears.
    await screen.findByRole("region", { name: "Set up my clients" });
  });

  it("stays hidden when the server-side preference says dismissed, even if local state has not caught up yet", async () => {
    updateLocalSettings("context", { experience_mode: "easy" });
    installPreferencesFetch(() => ({ welcome_clients_dismissed: true }));
    renderCard(USER);

    await waitFor(() => {
      expect(
        screen.queryByRole("region", { name: "Set up my clients" }),
      ).toBeNull();
    });
  });

  it("dismiss hides the card and PATCHes the server-side preference", async () => {
    updateLocalSettings("context", { experience_mode: "easy" });
    const calls = installPreferencesFetch(() => ({
      welcome_clients_dismissed: false,
    }));
    renderCard(USER);

    fireEvent.click(await screen.findByRole("button", { name: "Dismiss" }));

    expect(
      screen.queryByRole("region", { name: "Set up my clients" }),
    ).toBeNull();
    await waitFor(() => {
      const patch = calls.find((c) => c.method === "PATCH");
      expect(patch?.body).toEqual({ welcome_clients_dismissed: true });
    });
  });

  it("Get started stages a /welcome composer draft and navigates to a new chat", async () => {
    updateLocalSettings("context", { experience_mode: "easy" });
    installPreferencesFetch(() => ({ welcome_clients_dismissed: false }));
    renderCard(USER);

    fireEvent.click(await screen.findByRole("button", { name: "Get started" }));

    const draft = readComposerDraft(
      getSessionComposerDraftStorage(),
      buildComposerDraftKey({
        userId: USER.id,
        agentName: null,
        threadId: "new",
      }),
    );
    expect(draft?.skillName).toBe("welcome");
    expect(pushMock).toHaveBeenCalledWith("/workspace/chats/new");
  });

  it("for a session with no real account, uses local settings only and never calls the server", async () => {
    updateLocalSettings("context", { experience_mode: "easy" });
    const calls = installPreferencesFetch(() => ({
      welcome_clients_dismissed: false,
    }));
    renderCard(null);

    await screen.findByRole("region", { name: "Set up my clients" });

    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(
      screen.queryByRole("region", { name: "Set up my clients" }),
    ).toBeNull();
    expect(calls).toHaveLength(0);
  });
});
