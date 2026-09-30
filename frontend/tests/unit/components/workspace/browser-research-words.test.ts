import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "@rstest/core";

import {
  BROWSER_GENERIC,
  BROWSER_MESSAGES,
  browserWords,
  captureState,
} from "@/components/workspace/browser-research-words";

const SERVICE = resolve(
  __dirname,
  "../../../../../backend/app/gateway/browserbase_service.py",
);

describe("browserWords", () => {
  it("gives a stored code its sentence and never shows a raw code", () => {
    expect(browserWords("private_network_blocked")).toBe(
      "That address points to a private network, so it was not opened.",
    );
    expect(browserWords(new Error("provider_unconfigured"))).toBe(
      "Browserbase is not connected on this server.",
    );
    expect(browserWords("some_new_code")).toBe(BROWSER_GENERIC);
    expect(browserWords(null)).toBe(BROWSER_GENERIC);
  });

  it("passes a sentence through", () => {
    expect(browserWords("Browser research request failed")).toBe(
      "Browser research request failed",
    );
  });

  it("has words for every code the service raises or stores", () => {
    const source = readFileSync(SERVICE, "utf-8");
    const codes = new Set<string>();
    for (const match of source.matchAll(
      /(?:BrowserbaseError\(\s*|\["(?:reason|last_error)"\]\s*=\s*|phase\s*=\s*)["']([a-z][a-z0-9_]*)["']/g,
    ))
      codes.add(match[1]!);
    const safe = /safe_worker_codes\s*=\s*\{([^}]*)\}/.exec(source)?.[1] ?? "";
    for (const match of safe.matchAll(/["']([a-z][a-z0-9_]*)["']/g))
      codes.add(match[1]!);
    expect(codes.size).toBeGreaterThan(30);
    const missing = [...codes].filter((code) => !BROWSER_MESSAGES[code]);
    expect(missing).toEqual([]);
  });
});

describe("captureState", () => {
  it("uses the board's words: only running work is Working", () => {
    expect(captureState("running")).toEqual({
      label: "Working",
      tone: "active",
    });
    expect(captureState("queued").label).toBe("Queued");
    expect(captureState("completed")).toEqual({
      label: "Captured",
      tone: "ok",
    });
    expect(captureState("failed").tone).toBe("danger");
    expect(captureState("cancelled").label).toBe("Stopped");
  });
});
