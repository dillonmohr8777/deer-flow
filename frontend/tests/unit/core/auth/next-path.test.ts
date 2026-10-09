import { describe, expect, test } from "@rstest/core";

import {
  resolveAuthNextPath,
  validateAuthNextPath,
} from "@/core/auth/next-path";

describe("auth next path validation", () => {
  test("accepts local absolute paths", () => {
    expect(validateAuthNextPath("/workspace")).toBe("/workspace");
    expect(validateAuthNextPath("/workspace/chats/new?tab=recent#top")).toBe(
      "/workspace/chats/new?tab=recent#top",
    );
  });

  test("rejects external and ambiguous redirects", () => {
    expect(validateAuthNextPath(null)).toBeNull();
    expect(validateAuthNextPath("workspace")).toBeNull();
    expect(validateAuthNextPath("//evil.example")).toBeNull();
    expect(validateAuthNextPath("https://evil.example")).toBeNull();
    expect(validateAuthNextPath("/:evil")).toBeNull();
    expect(validateAuthNextPath("/\\evil.example")).toBeNull();
    expect(validateAuthNextPath("/foo\\bar")).toBeNull();
  });

  test("rejects control characters browsers would strip", () => {
    // "/\t/evil.example" is parsed by browsers as "//evil.example".
    for (const unsafe of [
      "/\t/evil.example",
      "/\n/evil.example",
      "/\r/evil.example",
      "/ /evil.example",
      "/\u0000x",
      "/\u007fx",
    ]) {
      expect(validateAuthNextPath(unsafe)).toBeNull();
    }
    expect(validateAuthNextPath("/invite")).toBe("/invite");
  });

  test("falls back for unsafe paths", () => {
    expect(resolveAuthNextPath("/\\evil.example")).toBe("/workspace");
    expect(resolveAuthNextPath("/safe", "/fallback")).toBe("/safe");
  });
});
