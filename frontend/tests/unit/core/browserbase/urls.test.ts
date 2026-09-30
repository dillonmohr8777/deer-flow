import { describe, expect, it } from "@rstest/core";

import { parseResearchUrls, publicResearchUrl } from "@/core/browserbase/urls";

describe("Browser research input", () => {
  it("normalizes public HTTPS inputs and bounds each batch", () => {
    expect(
      parseResearchUrls(
        " https://developers.openai.com/api/docs#tools\n\nhttps://docs.browserbase.com ",
      ),
    ).toEqual([
      "https://developers.openai.com/api/docs",
      "https://docs.browserbase.com/",
    ]);
    expect(() => parseResearchUrls(" ")).toThrow("Enter one to 3");
    expect(() =>
      parseResearchUrls(
        "https://a.com\nhttps://b.com\nhttps://c.com\nhttps://d.com",
      ),
    ).toThrow("Enter one to 3");
    expect(() =>
      parseResearchUrls("https://a.com\nhttps://a.com/#duplicate"),
    ).toThrow("Each page URL must be different");
  });

  it.each([
    "http://openai.com",
    "https://localhost",
    "https://host.local",
    "https://10.0.0.1",
    "https://2130706433",
    "https://0x7f000001",
    "https://[::1]",
    "https://user:password@openai.com",
    "https://openai.com:9443",
    "javascript:alert(1)",
    "//openai.com",
    "https://host.invalid",
  ])("rejects a visibly unsafe source %s", (url) => {
    expect(publicResearchUrl(url)).toBeNull();
  });
});
