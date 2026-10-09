import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

const mocks = rs.hoisted(() => ({
  fetch: rs.fn(),
  copy: rs.fn(),
}));

rs.mock("@/core/api/fetcher", () => ({
  fetch: mocks.fetch,
  getCsrfHeaders: () => ({}),
}));
rs.mock("@/core/clipboard", () => ({ writeTextToClipboard: mocks.copy }));

import { InviteSettingsPage } from "@/components/workspace/settings/invite-settings-page";
import { I18nProvider } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";

const t = enUS.settings.invite;
const TOKEN = "tok_SECRET-123_abc";
const FROZEN_DETAIL =
  "Workspace invitations are paused while workspace isolation is upgraded. Existing members keep their access.";

function jsonResponse(status: number, body: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

type Workspaces = {
  workspaces: { id: string; name: string; role: string }[];
  active_workspace_id: string | null;
};

const ADMIN_WORKSPACES: Workspaces = {
  workspaces: [
    { id: "org-a", name: "Alpha", role: "owner" },
    { id: "org-b", name: "Momentum", role: "admin" },
    { id: "org-c", name: "Gamma", role: "member" },
  ],
  active_workspace_id: "org-b",
};

function asSelect(element: HTMLElement): HTMLSelectElement {
  if (!(element instanceof HTMLSelectElement)) throw new Error("not a select");
  return element;
}

function asInput(element: HTMLElement): HTMLInputElement {
  if (!(element instanceof HTMLInputElement)) throw new Error("not an input");
  return element;
}

let createResponse: () => Promise<Response>;
let workspacesResponse: () => Promise<Response>;

function createdBody() {
  return {
    id: "inv-1",
    token: TOKEN,
    expires_at: "2026-10-01T12:00:00Z",
    email: "new@example.com",
    workspace_name: "Momentum",
  };
}

function mount() {
  return render(
    <I18nProvider initialLocale="en-US">
      <InviteSettingsPage />
    </I18nProvider>,
  );
}

async function fillAndSubmit(email = "new@example.com") {
  const input = await screen.findByLabelText(t.emailLabel);
  fireEvent.change(input, { target: { value: email } });
  fireEvent.click(screen.getByRole("button", { name: t.submit }));
}

function createCalls() {
  return mocks.fetch.mock.calls.filter(
    ([url]) => typeof url === "string" && url.includes("/invitations"),
  ) as [string, RequestInit][];
}

beforeEach(() => {
  mocks.fetch.mockReset();
  mocks.copy.mockReset();
  mocks.copy.mockResolvedValue(true);
  workspacesResponse = async () => jsonResponse(200, ADMIN_WORKSPACES);
  createResponse = async () => jsonResponse(201, createdBody());
  mocks.fetch.mockImplementation(async (url: string) =>
    url.includes("/invitations") ? createResponse() : workspacesResponse(),
  );
  window.localStorage.clear();
  window.sessionStorage.clear();
});

afterEach(() => {
  cleanup();
  rs.restoreAllMocks();
});

describe("InviteSettingsPage gating", () => {
  it("shows the form to an owner/admin, defaulting to the active workspace", async () => {
    mount();
    const org = asSelect(await screen.findByLabelText(t.workspaceLabel));
    expect(org.value).toBe("org-b");
    const names = Array.from(org.options).map((o) => o.textContent);
    expect(names).toEqual(["Alpha", "Momentum"]);
  });

  it("explains that only admins can invite when the caller is a plain member", async () => {
    workspacesResponse = async () =>
      jsonResponse(200, {
        workspaces: [{ id: "org-c", name: "Gamma", role: "member" }],
        active_workspace_id: "org-c",
      });
    mount();
    expect(await screen.findByText(t.notAllowed)).toBeTruthy();
    expect(screen.queryByLabelText(t.emailLabel)).toBeNull();
  });

  it("explains it when there is no shared workspace (private only)", async () => {
    workspacesResponse = async () =>
      jsonResponse(200, { workspaces: [], active_workspace_id: null });
    mount();
    expect(await screen.findByText(t.notAllowed)).toBeTruthy();
    expect(screen.queryByLabelText(t.emailLabel)).toBeNull();
  });

  it("shows a retryable error when the workspace list fails to load", async () => {
    workspacesResponse = async () => jsonResponse(500, { detail: "boom" });
    mount();
    expect(await screen.findByText(t.loadFailed)).toBeTruthy();
    workspacesResponse = async () => jsonResponse(200, ADMIN_WORKSPACES);
    fireEvent.click(screen.getByRole("button", { name: t.retry }));
    expect(await screen.findByLabelText(t.emailLabel)).toBeTruthy();
  });
});

describe("InviteSettingsPage form", () => {
  it("offers member, admin and client roles, member first", async () => {
    mount();
    const role = asSelect(await screen.findByLabelText(t.roleLabel));
    expect(Array.from(role.options).map((o) => o.value)).toEqual([
      "member",
      "admin",
      "client",
    ]);
    expect(role.value).toBe("member");
  });

  it("posts organization_id, email and role", async () => {
    mount();
    fireEvent.change(await screen.findByLabelText(t.roleLabel), {
      target: { value: "client" },
    });
    await fillAndSubmit("  New@Example.com ");
    await screen.findByLabelText(t.linkLabel);
    const calls = createCalls();
    expect(calls).toHaveLength(1);
    const [url, init] = calls[0]!;
    expect(url).toContain("/api/v1/auth/invitations");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      organization_id: "org-b",
      email: "New@Example.com",
      role: "client",
    });
  });

  it("does not post an empty email", async () => {
    mount();
    fireEvent.click(await screen.findByRole("button", { name: t.submit }));
    expect(createCalls()).toHaveLength(0);
  });
});

describe("InviteSettingsPage success", () => {
  it("shows the one-time link in the fragment with a shown-once warning", async () => {
    mount();
    await fillAndSubmit();
    const link = asInput(await screen.findByLabelText(t.linkLabel));
    expect(link.value).toBe(`${window.location.origin}/invite#token=${TOKEN}`);
    expect(link.value).not.toContain("?");
    expect(screen.getByText(t.shownOnce)).toBeTruthy();
    expect(screen.getByRole("button", { name: t.copy })).toBeTruthy();
    expect(screen.queryByLabelText(t.emailLabel)).toBeNull();
  });

  it("copies the link and confirms", async () => {
    mount();
    await fillAndSubmit();
    const link = asInput(await screen.findByLabelText(t.linkLabel));
    fireEvent.click(screen.getByRole("button", { name: t.copy }));
    await waitFor(() => expect(mocks.copy).toHaveBeenCalledWith(link.value));
    expect(await screen.findByRole("button", { name: t.copied })).toBeTruthy();
  });

  it("says so when copying fails", async () => {
    mocks.copy.mockResolvedValue(false);
    mount();
    await fillAndSubmit();
    fireEvent.click(await screen.findByRole("button", { name: t.copy }));
    expect(await screen.findByText(t.copyFailed)).toBeTruthy();
  });

  it("never writes the token to storage, the URL query or the console", async () => {
    const spies = (["log", "info", "warn", "error", "debug"] as const).map(
      (m) => rs.spyOn(console, m).mockImplementation(() => undefined),
    );
    mount();
    await fillAndSubmit();
    await screen.findByLabelText(t.linkLabel);

    for (const store of [window.localStorage, window.sessionStorage]) {
      for (let i = 0; i < store.length; i++) {
        const key = store.key(i)!;
        expect(key).not.toContain(TOKEN);
        expect(store.getItem(key)).not.toContain(TOKEN);
      }
    }
    expect(window.location.search).not.toContain(TOKEN);
    expect(window.location.href).not.toContain(TOKEN);
    for (const spy of spies) {
      expect(JSON.stringify(spy.mock.calls)).not.toContain(TOKEN);
    }
  });

  it("clears the link when starting another invite", async () => {
    mount();
    await fillAndSubmit();
    await screen.findByLabelText(t.linkLabel);
    fireEvent.click(screen.getByRole("button", { name: t.inviteAnother }));
    expect(await screen.findByLabelText(t.emailLabel)).toBeTruthy();
    expect(screen.queryByLabelText(t.linkLabel)).toBeNull();
    expect(document.body.innerHTML).not.toContain(TOKEN);
  });
});

describe("InviteSettingsPage failures", () => {
  it("shows the paused message on the frozen 403", async () => {
    createResponse = async () => jsonResponse(403, { detail: FROZEN_DETAIL });
    mount();
    await fillAndSubmit();
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByText(t.errors.frozen)).toBeTruthy();
    expect(screen.queryByLabelText(t.linkLabel)).toBeNull();
  });

  it("shows the role message on any other 403", async () => {
    createResponse = async () =>
      jsonResponse(403, { detail: "Only an active workspace owner or admin" });
    mount();
    await fillAndSubmit();
    expect(await screen.findByText(t.errors.forbidden)).toBeTruthy();
  });

  it("shows the email message on a 422 for the email field", async () => {
    createResponse = async () =>
      jsonResponse(422, {
        detail: [{ loc: ["body", "email"], msg: "bad", type: "value_error" }],
      });
    mount();
    await fillAndSubmit("not-an-email");
    expect(await screen.findByText(t.errors.invalidEmail)).toBeTruthy();
  });

  it("shows the conflict message on a 409", async () => {
    createResponse = async () => jsonResponse(409, { detail: "exists" });
    mount();
    await fillAndSubmit();
    expect(await screen.findByText(t.errors.conflict)).toBeTruthy();
  });

  it("shows the network message when the request throws, and keeps the form", async () => {
    createResponse = async () => {
      throw new TypeError("Failed to fetch");
    };
    mount();
    await fillAndSubmit();
    expect(await screen.findByText(t.errors.network)).toBeTruthy();
    expect(asInput(screen.getByLabelText(t.emailLabel)).value).toBe(
      "new@example.com",
    );
  });
});
