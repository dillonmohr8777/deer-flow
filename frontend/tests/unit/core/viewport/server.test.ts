import { describe, expect, it, rs } from "@rstest/core";

const MOBILE_UA =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1";
const DESKTOP_UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36";

const mockHeaders = rs.fn();
rs.mock("next/headers", () => ({
  headers: mockHeaders,
}));

async function loadServer() {
  rs.resetModules();
  return await import("@/core/viewport/server");
}

// useIsMobile's flash fix (hooks/use-mobile.ts) depends on this hint reading
// the real request, so it is worth pinning both branches directly rather
// than only through the hook's own tests, which never mount a provider.
describe("detectIsMobileServer", () => {
  it("is true for a phone User-Agent", async () => {
    mockHeaders.mockResolvedValueOnce(new Headers({ "user-agent": MOBILE_UA }));
    const { detectIsMobileServer } = await loadServer();
    expect(await detectIsMobileServer()).toBe(true);
  });

  it("is false for a desktop User-Agent", async () => {
    mockHeaders.mockResolvedValueOnce(
      new Headers({ "user-agent": DESKTOP_UA }),
    );
    const { detectIsMobileServer } = await loadServer();
    expect(await detectIsMobileServer()).toBe(false);
  });

  it("is false for a missing User-Agent", async () => {
    mockHeaders.mockResolvedValueOnce(new Headers());
    const { detectIsMobileServer } = await loadServer();
    expect(await detectIsMobileServer()).toBe(false);
  });
});
