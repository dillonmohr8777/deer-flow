import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

import LoginPage from "@/app/(auth)/login/page";
import { enUS } from "@/core/i18n/locales/en-US";

const mocks = rs.hoisted(() => ({
  push: rs.fn(),
}));

rs.mock("next/navigation", () => ({
  useRouter: () => ({ push: mocks.push }),
  useSearchParams: () => new URLSearchParams(),
}));
rs.mock("next-themes", () => ({
  useTheme: () => ({ theme: "light", resolvedTheme: "light" }),
}));
rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: () => ({ isAuthenticated: false }),
}));
rs.mock("@/core/i18n/hooks", () => ({ useI18n: () => ({ t: enUS }) }));

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status });
}

function routeFetch(
  overrides: Partial<Record<string, () => Response | Promise<Response>>>,
) {
  return async (input: RequestInfo | URL) => {
    const url =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : input.url;
    if (url.includes("/api/v1/auth/providers")) {
      return jsonResponse({ providers: [] });
    }
    if (url.includes("/api/v1/auth/setup-status")) {
      return jsonResponse({ needs_setup: false, registration_enabled: true });
    }
    const handler = Object.entries(overrides).find(([key]) =>
      url.includes(key),
    )?.[1];
    if (handler) return handler();
    throw new Error(`Unexpected fetch: ${url}`);
  };
}

async function submitPassword(
  email = "alice@example.com",
  password = "correct horse",
) {
  fireEvent.change(screen.getByLabelText("Email"), {
    target: { value: email },
  });
  fireEvent.change(screen.getByLabelText("Password"), {
    target: { value: password },
  });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
  await screen.findByText(
    "Enter the 6-digit code from your authenticator app.",
  );
}

beforeEach(() => {
  mocks.push.mockReset();
});

afterEach(() => {
  cleanup();
  rs.restoreAllMocks();
});

describe("login MFA step", () => {
  it("shows the MFA step instead of redirecting when login/local returns mfa_required", async () => {
    const loginLocal = rs.fn(() =>
      jsonResponse({ mfa_required: true, challenge: "challenge-123" }),
    );
    rs.spyOn(globalThis, "fetch").mockImplementation(
      routeFetch({ "/api/v1/auth/login/local": loginLocal }),
    );
    render(<LoginPage />);

    await submitPassword();

    expect(
      screen.getByRole("heading", {
        level: 1,
        name: "Two-factor verification",
      }),
    ).toBeTruthy();
    expect(screen.getByPlaceholderText("123456")).toBeTruthy();
    expect(mocks.push).not.toHaveBeenCalled();
  });

  it("exchanges the challenge and code for a session, then redirects", async () => {
    const loginMfa = rs.fn(() =>
      jsonResponse({ expires_in: 3600, needs_setup: false }),
    );
    rs.spyOn(globalThis, "fetch").mockImplementation(
      routeFetch({
        "/api/v1/auth/login/local": () =>
          jsonResponse({ mfa_required: true, challenge: "challenge-123" }),
        "/api/v1/auth/login/mfa": loginMfa,
      }),
    );
    render(<LoginPage />);
    await submitPassword();

    fireEvent.change(screen.getByPlaceholderText("123456"), {
      target: { value: "654321" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Verify" }));

    await waitFor(() => expect(mocks.push).toHaveBeenCalledWith("/workspace"));
    expect(loginMfa).toHaveBeenCalled();
    const [, init] = (
      globalThis.fetch as ReturnType<typeof rs.fn>
    ).mock.calls.find(([u]) => String(u).includes("/login/mfa"))!;
    expect(JSON.parse(init.body as string)).toEqual({
      challenge: "challenge-123",
      remember_me: true,
      code: "654321",
    });
  });

  it("shows an error and does not redirect on an invalid code", async () => {
    rs.spyOn(globalThis, "fetch").mockImplementation(
      routeFetch({
        "/api/v1/auth/login/local": () =>
          jsonResponse({ mfa_required: true, challenge: "challenge-123" }),
        "/api/v1/auth/login/mfa": () =>
          jsonResponse(
            {
              code: "invalid_credentials",
              message: "Invalid or expired verification challenge",
            },
            401,
          ),
      }),
    );
    render(<LoginPage />);
    await submitPassword();

    fireEvent.change(screen.getByPlaceholderText("123456"), {
      target: { value: "000000" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Verify" }));

    expect(
      await screen.findByText("Invalid or expired verification challenge"),
    ).toBeTruthy();
    expect(mocks.push).not.toHaveBeenCalled();
  });

  it("switches to a recovery code and submits recovery_code instead of code", async () => {
    const loginMfa = rs.fn(() =>
      jsonResponse({ expires_in: 3600, needs_setup: false }),
    );
    rs.spyOn(globalThis, "fetch").mockImplementation(
      routeFetch({
        "/api/v1/auth/login/local": () =>
          jsonResponse({ mfa_required: true, challenge: "challenge-123" }),
        "/api/v1/auth/login/mfa": loginMfa,
      }),
    );
    render(<LoginPage />);
    await submitPassword();

    fireEvent.click(
      screen.getByRole("button", { name: "Use a recovery code instead" }),
    );
    expect(screen.getByPlaceholderText("xxxxx-xxxxx")).toBeTruthy();
    fireEvent.change(screen.getByPlaceholderText("xxxxx-xxxxx"), {
      target: { value: "abcde-12345" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Verify" }));

    await waitFor(() => expect(mocks.push).toHaveBeenCalled());
    const [, init] = (
      globalThis.fetch as ReturnType<typeof rs.fn>
    ).mock.calls.find(([u]) => String(u).includes("/login/mfa"))!;
    expect(JSON.parse(init.body as string)).toEqual({
      challenge: "challenge-123",
      remember_me: true,
      recovery_code: "abcde-12345",
    });
  });

  it("Back to sign in returns to the password form", async () => {
    rs.spyOn(globalThis, "fetch").mockImplementation(
      routeFetch({
        "/api/v1/auth/login/local": () =>
          jsonResponse({ mfa_required: true, challenge: "challenge-123" }),
      }),
    );
    render(<LoginPage />);
    await submitPassword();

    fireEvent.click(screen.getByRole("button", { name: "Back to sign in" }));

    expect(
      screen.getByRole("heading", { level: 1, name: "Sign in to MomoBot" }),
    ).toBeTruthy();
    expect(screen.getByLabelText("Password")).toBeTruthy();
  });
});
