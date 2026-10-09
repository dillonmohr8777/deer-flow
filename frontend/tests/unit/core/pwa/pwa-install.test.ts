import { afterEach, describe, expect, it, rs } from "@rstest/core";

import {
  isInstalledWebApp,
  isIosDevice,
  registerPublicServiceWorker,
} from "@/core/pwa/install";

afterEach(() => {
  rs.unstubAllGlobals();
});

describe("PWA installation support", () => {
  it("recognizes iPhone and desktop-mode iPad without mistaking a Mac for iOS", () => {
    expect(isIosDevice("Mozilla iPhone", "iPhone", 5)).toBe(true);
    expect(isIosDevice("Mozilla Macintosh", "MacIntel", 5)).toBe(true);
    expect(isIosDevice("Mozilla Macintosh", "MacIntel", 0)).toBe(false);
    expect(isIosDevice("Mozilla Android", "Linux", 5)).toBe(false);
  });

  it("hides installation guidance only for an installed display mode", () => {
    expect(isInstalledWebApp(true, undefined)).toBe(true);
    expect(isInstalledWebApp(false, true)).toBe(true);
    expect(isInstalledWebApp(false, false)).toBe(false);
  });

  it("does not register a worker over an insecure or unsupported connection", async () => {
    const register = rs.fn();
    rs.stubGlobal("window", { isSecureContext: false });
    rs.stubGlobal("navigator", { serviceWorker: { register } });
    expect(await registerPublicServiceWorker()).toBeNull();
    expect(register).not.toHaveBeenCalled();
    rs.stubGlobal("window", { isSecureContext: true });
    rs.stubGlobal("navigator", {});
    expect(await registerPublicServiceWorker()).toBeNull();
  });

  it("registers the public-only worker without a cached worker update", async () => {
    const registration = { scope: "https://momo.example.test/" };
    const register = rs.fn(async () => registration);
    rs.stubGlobal("window", { isSecureContext: true });
    rs.stubGlobal("navigator", { serviceWorker: { register } });
    expect(await registerPublicServiceWorker()).toBe(registration);
    expect(register).toHaveBeenCalledWith("/sw.js", {
      scope: "/",
      updateViaCache: "none",
    });
  });
});
