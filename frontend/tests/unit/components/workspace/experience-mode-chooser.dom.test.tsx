import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

import { ExperienceModeChooser } from "@/components/workspace/experience-mode-chooser";
import { I18nProvider } from "@/core/i18n/context";

const mocks = rs.hoisted(() => ({
  fetch: rs.fn(),
  setSettings: rs.fn(),
}));
rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: () => ({ user: { id: "alice" } }),
}));
rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "" }));
rs.mock("@/core/static-mode", () => ({ isStaticWebsiteOnly: () => false }));
rs.mock("@/core/api/fetcher", () => ({ fetch: mocks.fetch }));
rs.mock("@/core/settings", () => ({
  useLocalSettings: () => [{}, mocks.setSettings],
}));

function Chooser() {
  return (
    <I18nProvider initialLocale="en-US">
      <ExperienceModeChooser />
    </I18nProvider>
  );
}

beforeEach(() => {
  mocks.fetch.mockReset();
  mocks.setSettings.mockReset();
});
afterEach(() => {
  cleanup();
  rs.restoreAllMocks();
});

describe("first-login experience choice", () => {
  it("keeps the choice open on HTTP failure and closes only after a successful retry", async () => {
    mocks.fetch
      .mockResolvedValueOnce(Response.json({ experience_mode: null }))
      .mockResolvedValueOnce(Response.json({}, { status: 500 }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    render(<Chooser />);
    fireEvent.click(await screen.findByRole("button", { name: /Easy/ }));
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(mocks.setSettings).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /Easy/ }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(mocks.setSettings).toHaveBeenCalledWith("context", {
      experience_mode: "easy",
      mode: "flash",
    });
    const init = mocks.fetch.mock.calls[2]![1] as RequestInit;
    expect(init.headers).toMatchObject({ "X-Expected-User-Id": "alice" });
    expect(JSON.parse(init.body as string)).toEqual({
      experience_mode: "easy",
      mode: "flash",
    });
  });

  it("recovers from a stalled save and allows a retry", async () => {
    const timeout = new AbortController();
    const timeoutSpy = rs
      .spyOn(AbortSignal, "timeout")
      .mockReturnValue(timeout.signal);
    mocks.fetch
      .mockResolvedValueOnce(Response.json({ experience_mode: null }))
      .mockImplementationOnce(
        (_path: string, init: RequestInit) =>
          new Promise((_resolve, reject) => {
            init.signal?.addEventListener("abort", () =>
              reject(new Error("aborted")),
            );
          }),
      )
      .mockResolvedValueOnce(Response.json({ experience_mode: "medium" }));
    render(<Chooser />);
    fireEvent.click(await screen.findByRole("button", { name: /Easy/ }));
    expect(timeoutSpy).toHaveBeenCalledWith(15000);
    expect(
      screen.getByRole("button", { name: /Easy/ }).hasAttribute("disabled"),
    ).toBe(true);
    await act(async () => timeout.abort());
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(mocks.setSettings).not.toHaveBeenCalled();
    timeoutSpy.mockRestore();
    fireEvent.click(screen.getByRole("button", { name: "Skip for now" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(mocks.setSettings).toHaveBeenCalledWith("context", {
      experience_mode: "medium",
      mode: "pro",
    });
  });

  it("aborts an in-flight save on unmount and ignores a late response", async () => {
    let resolveSave!: (response: Response) => void;
    mocks.fetch
      .mockResolvedValueOnce(Response.json({ experience_mode: null }))
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveSave = resolve;
          }),
      );
    const view = render(<Chooser />);
    fireEvent.click(await screen.findByRole("button", { name: /Easy/ }));
    const signal = (mocks.fetch.mock.calls[1]![1] as RequestInit).signal!;
    view.unmount();
    expect(signal.aborted).toBe(true);
    await act(async () =>
      resolveSave(Response.json({ experience_mode: "easy" })),
    );
    expect(mocks.setSettings).not.toHaveBeenCalled();
  });
});
