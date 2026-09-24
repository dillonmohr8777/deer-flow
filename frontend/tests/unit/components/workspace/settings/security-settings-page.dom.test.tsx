import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

const mocks = rs.hoisted(() => ({
  user: { mfa_enabled: false } as { mfa_enabled: boolean },
  refreshUser: rs.fn(),
  fetch: rs.fn(),
}));

rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: () => ({ user: mocks.user, refreshUser: mocks.refreshUser }),
}));

rs.mock("@/core/api/fetcher", () => ({
  fetch: mocks.fetch,
  getCsrfHeaders: () => ({}),
}));

import { SecuritySettingsPage } from "@/components/workspace/settings/security-settings-page";
import { I18nProvider } from "@/core/i18n/context";

function jsonResponse(body: unknown, ok = true) {
  return { ok, json: async () => body } as Response;
}

function mount() {
  return render(
    <I18nProvider initialLocale="en-US">
      <SecuritySettingsPage />
    </I18nProvider>,
  );
}

beforeEach(() => {
  mocks.user.mfa_enabled = false;
  mocks.fetch.mockReset();
  mocks.refreshUser.mockReset();
});

afterEach(() => {
  cleanup();
});

describe("SecuritySettingsPage", () => {
  it("shows the disabled status and an enable button by default", () => {
    mount();
    expect(
      screen.getByText(
        "It's off. Turn it on for an extra layer of protection.",
      ),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Turn on two-factor authentication" }),
    ).toBeTruthy();
  });

  it("shows the enabled status and a disable button when mfa_enabled is true", () => {
    mocks.user.mfa_enabled = true;
    mount();
    expect(screen.getByText("Two-factor authentication is on.")).toBeTruthy();
    expect(
      screen.getByRole("button", {
        name: "Turn off two-factor authentication",
      }),
    ).toBeTruthy();
  });

  it("starts enrollment and shows the QR code and manual-entry secret", async () => {
    mocks.fetch.mockResolvedValueOnce(
      jsonResponse({
        secret: "JBSWY3DPEHPK3PXP",
        otpauth_uri: "otpauth://totp/MomoBot:alice?secret=JBSWY3DPEHPK3PXP",
      }),
    );
    mount();
    fireEvent.click(
      screen.getByRole("button", { name: "Turn on two-factor authentication" }),
    );

    await screen.findByText("JBSWY3DPEHPK3PXP");
    expect(mocks.fetch).toHaveBeenCalledWith(
      "/api/v1/auth/mfa/enroll/start",
      expect.objectContaining({ method: "POST" }),
    );
    expect(
      screen.getByRole("button", { name: "Confirm and turn on" }),
    ).toBeTruthy();
  });

  it("confirms enrollment, shows the ten recovery codes once, and refreshes the user", async () => {
    const recoveryCodes = Array.from(
      { length: 10 },
      (_, i) => `code${i}-aaaaa`,
    );
    mocks.fetch
      .mockResolvedValueOnce(
        jsonResponse({ secret: "SECRET123", otpauth_uri: "otpauth://totp/x" }),
      )
      .mockResolvedValueOnce(jsonResponse({ recovery_codes: recoveryCodes }));
    mount();
    fireEvent.click(
      screen.getByRole("button", { name: "Turn on two-factor authentication" }),
    );
    await screen.findByText("SECRET123");

    fireEvent.change(screen.getByPlaceholderText("123456"), {
      target: { value: "654321" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Confirm and turn on" }),
    );

    await screen.findByText(recoveryCodes[0]!);
    expect(mocks.fetch).toHaveBeenLastCalledWith(
      "/api/v1/auth/mfa/enroll/confirm",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ code: "654321" }),
      }),
    );
    for (const rc of recoveryCodes) {
      expect(screen.getByText(rc)).toBeTruthy();
    }
    expect(mocks.refreshUser).toHaveBeenCalled();
  });

  it("shows a generic error and stays enrolling when the code is rejected", async () => {
    mocks.fetch
      .mockResolvedValueOnce(
        jsonResponse({ secret: "SECRET123", otpauth_uri: "otpauth://totp/x" }),
      )
      .mockResolvedValueOnce(
        jsonResponse(
          { code: "invalid_credentials", message: "Invalid verification code" },
          false,
        ),
      );
    mount();
    fireEvent.click(
      screen.getByRole("button", { name: "Turn on two-factor authentication" }),
    );
    await screen.findByText("SECRET123");
    fireEvent.change(screen.getByPlaceholderText("123456"), {
      target: { value: "000000" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Confirm and turn on" }),
    );

    expect(await screen.findByText("Invalid verification code")).toBeTruthy();
    expect(mocks.refreshUser).not.toHaveBeenCalled();
  });

  it("disables MFA with password + code, leaves the confirmation form, and refreshes the user", async () => {
    // mfa_enabled here is the AuthProvider-owned mock, not local component
    // state; the real flag only flips once refreshUser() re-fetches /me, so
    // this asserts the wizard returns to idle (the form is gone) rather than
    // asserting a status string that this test double can't actually update.
    mocks.user.mfa_enabled = true;
    mocks.fetch.mockResolvedValueOnce(jsonResponse({ message: "ok" }));
    mount();
    fireEvent.click(
      screen.getByRole("button", {
        name: "Turn off two-factor authentication",
      }),
    );

    fireEvent.change(screen.getByPlaceholderText("Password"), {
      target: { value: "hunter2" },
    });
    fireEvent.change(screen.getByPlaceholderText("6-digit code"), {
      target: { value: "111111" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Turn off" }));

    await screen.findByRole("button", {
      name: "Turn off two-factor authentication",
    });
    expect(screen.queryByPlaceholderText("Password")).toBeNull();
    expect(mocks.fetch).toHaveBeenCalledWith(
      "/api/v1/auth/mfa/disable",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ password: "hunter2", code: "111111" }),
      }),
    );
    expect(mocks.refreshUser).toHaveBeenCalled();
  });

  it("switches the disable form to a recovery code field", async () => {
    mocks.user.mfa_enabled = true;
    mount();
    fireEvent.click(
      screen.getByRole("button", {
        name: "Turn off two-factor authentication",
      }),
    );
    expect(screen.getByPlaceholderText("6-digit code")).toBeTruthy();

    fireEvent.click(
      screen.getByRole("button", { name: "Use a recovery code instead" }),
    );
    expect(screen.getByPlaceholderText("Recovery code")).toBeTruthy();
  });
});
