import { afterEach, expect, rs, test } from "@rstest/core";

import {
  DEFAULT_LOCAL_SETTINGS,
  getLocalSettings,
  getResolvedMode,
  getThreadModelName,
  saveLocalSettings,
  saveThreadModelName,
} from "@/core/settings/local";

afterEach(() => {
  rs.unstubAllGlobals();
});

test("planning and delegation stay selectable without provider thinking", () => {
  for (const supportsThinking of [false, true]) {
    for (const mode of ["flash", "pro", "ultra"] as const) {
      expect(getResolvedMode(mode, supportsThinking)).toBe(mode);
    }
  }
  expect(getResolvedMode("thinking", false)).toBe("flash");
  expect(getResolvedMode("thinking", true)).toBe("thinking");
  expect(getResolvedMode(undefined, false)).toBe("flash");
  expect(getResolvedMode(undefined, true)).toBe("pro");
});

test("defaults token usage to header total plus per-turn breakdown", () => {
  expect(DEFAULT_LOCAL_SETTINGS.tokenUsage).toEqual({
    headerTotal: true,
    inlineMode: "per_turn",
  });
});

test("falls back when localStorage access is blocked", () => {
  rs.stubGlobal("window", {
    get localStorage() {
      throw new DOMException("Blocked", "SecurityError");
    },
  });

  expect(getLocalSettings()).toEqual(DEFAULT_LOCAL_SETTINGS);
  expect(getThreadModelName("thread-1")).toBeUndefined();
  expect(() => saveLocalSettings(DEFAULT_LOCAL_SETTINGS)).not.toThrow();
  expect(() => saveThreadModelName("thread-1", "model-1")).not.toThrow();
});
