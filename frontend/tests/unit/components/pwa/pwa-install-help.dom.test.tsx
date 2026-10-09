import { afterEach, describe, expect, it, rs } from "@rstest/core";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";

import { InstallHelp } from "@/components/pwa/install-help";
import { InstallHelpDialog } from "@/components/pwa/install-help-dialog";
import { INSTALL_HELP_DISMISSED_KEY } from "@/core/pwa/install";

rs.mock("next/navigation", () => ({ usePathname: () => "/workspace/openai" }));
// The browser suite exercises the real lazy dialog boundary. These tests own
// eligibility, persistence, event subscriptions and the dialog's actual content.
rs.mock("next/dynamic", () => ({ default: () => () => null }));

function iphone(standalone = false) {
  rs.stubGlobal("navigator", {
    userAgent: "Mozilla/5.0 (iPhone; CPU iPhone OS 26_0 like Mac OS X)",
    platform: "iPhone",
    maxTouchPoints: 5,
    standalone,
  });
}

afterEach(() => {
  cleanup();
  localStorage.clear();
  rs.unstubAllGlobals();
  rs.restoreAllMocks();
});

describe("MomoBot installation help", () => {
  it("shows guidance in an iPhone browser and suppresses it in an installed app", () => {
    iphone();
    const { unmount } = render(<InstallHelp />);
    expect(
      screen.getByRole("button", { name: "Install MomoBot" }),
    ).toBeDefined();
    unmount();
    iphone(true);
    render(<InstallHelp />);
    expect(
      screen.queryByRole("button", { name: "Install MomoBot" }),
    ).toBeNull();
  });

  it("stores only a dismissal flag and respects it on the next visit", () => {
    iphone();
    const { unmount } = render(<InstallHelp />);
    fireEvent.click(
      screen.getByRole("button", { name: "Dismiss install help" }),
    );
    expect(
      screen.queryByRole("button", { name: "Install MomoBot" }),
    ).toBeNull();
    expect(localStorage.length).toBe(1);
    expect(localStorage.getItem(INSTALL_HELP_DISMISSED_KEY)).toBe("1");
    unmount();
    render(<InstallHelp />);
    expect(
      screen.queryByRole("button", { name: "Install MomoBot" }),
    ).toBeNull();
  });

  it("offers native installation only after the browser supplies a real prompt", () => {
    rs.stubGlobal("navigator", {
      userAgent: "desktop",
      platform: "MacIntel",
      maxTouchPoints: 0,
    });
    render(<InstallHelp />);
    expect(
      screen.queryByRole("button", { name: "Install MomoBot" }),
    ).toBeNull();
    const event = new Event("beforeinstallprompt", { cancelable: true });
    Object.defineProperty(event, "prompt", {
      value: rs.fn(async () => undefined),
    });
    act(() => {
      window.dispatchEvent(event);
    });
    expect(event.defaultPrevented).toBe(true);
    expect(
      screen.getByRole("button", { name: "Install MomoBot" }),
    ).toBeDefined();
    act(() => {
      window.dispatchEvent(new Event("appinstalled"));
    });
    expect(
      screen.queryByRole("button", { name: "Install MomoBot" }),
    ).toBeNull();
  });

  it("removes installation and display-mode listeners when unmounted", () => {
    iphone();
    const remove = rs.spyOn(window, "removeEventListener");
    const { unmount } = render(<InstallHelp />);
    unmount();
    expect(remove).toHaveBeenCalledWith(
      "beforeinstallprompt",
      expect.any(Function),
    );
    expect(remove).toHaveBeenCalledWith("appinstalled", expect.any(Function));
  });

  it("explains Safari’s current Home Screen steps without promising offline agent work", () => {
    render(
      <InstallHelpDialog
        ios
        nativePromptAvailable={false}
        prompting={false}
        promptFailed={false}
        onOpenChange={() => undefined}
        onInstall={() => undefined}
        onCloseFocus={() => undefined}
      />,
    );
    expect(
      screen.getByRole("dialog", { name: "Keep MomoBot one tap away" }),
    ).toBeDefined();
    expect(screen.getByText(/Open as Web App/)).toBeDefined();
    expect(screen.getByText(/Edit Actions/)).toBeDefined();
    expect(screen.getByText(/internet connection is required/)).toBeDefined();
    expect(screen.queryByRole("button", { name: "Install app" })).toBeNull();
  });

  it("passes an explicit native install click to the browser prompt owner", () => {
    const install = rs.fn();
    render(
      <InstallHelpDialog
        ios={false}
        nativePromptAvailable
        prompting={false}
        promptFailed={false}
        onOpenChange={() => undefined}
        onInstall={install}
        onCloseFocus={() => undefined}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Install app" }));
    expect(install).toHaveBeenCalledTimes(1);
  });
});
