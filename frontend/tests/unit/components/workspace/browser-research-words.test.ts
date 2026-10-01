import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "@rstest/core";

import {
  BROWSER_GENERIC,
  BROWSER_MESSAGES,
  browserWords,
  captureState,
} from "@/components/workspace/browser-research-words";

const GATEWAY = resolve(__dirname, "../../../../../backend/app/gateway");
const SOURCES = [
  resolve(GATEWAY, "browserbase_service.py"),
  resolve(GATEWAY, "routers/browserbase_research.py"),
];

// Every place a code is raised or stored: the exception, the stored reason,
// last_error and phase, keyword forms, and the router's HTTP detail.
const SITE =
  /BrowserbaseError\(|\[["'](?:reason|last_error)["']\]\s*=|\blast_error\s*=|\bphase\s*=|\bcode\s*=|\bdetail\s*=/;
// The only sites allowed to pass a code on through a variable, matched as
// whole lines so nothing can be appended to them: each passes on a code
// that was itself raised at a literal site, or the worker code checked
// against safe_worker_codes. A new propagation line must be reviewed here.
const PROPAGATED_LINES = new Set([
  "self.code = code",
  'state["reason"] = error.code',
  'data["last_error"] = error.code',
  'code = getattr(error, "code", None)',
  'data["last_error"] = code if isinstance(code, str) and code in safe_worker_codes else phase',
  "raise ValueError(error.code) from None",
  "raise HTTPException(error.status_code, detail=error.code) from None",
]);

const REVIEWED_NAMES = new Set([
  // Python keywords and constants that cannot carry a code.
  ...[
    "if",
    "else",
    "or",
    "and",
    "not",
    "in",
    "is",
    "from",
    "None",
    "True",
    "False",
  ],
  // `state["reason"]` (masked to `state[key]`), assigned only at literal
  // reason sites; `self.enabled()`; `phase`, assigned only at literal sites.
  ...["state", "key", "self", "enabled", "phase"],
]);

function sitesAndCodes() {
  const codes = new Set<string>();
  const unreviewed: string[] = [];
  for (const file of SOURCES) {
    const lines = readFileSync(file, "utf-8").split("\n");
    lines.forEach((line, index) => {
      const site = SITE.exec(line);
      if (!site || /^\s*(?:#|class |def )/.test(line)) return;
      // Subscripts (`state["reason"]`) and getattr names are keys, not codes.
      const value = line
        .slice(site.index + site[0].length)
        .replace(/\[\s*["'][^"']*["']\s*\]/g, "[key]")
        .replace(/getattr\([^)]*\)/g, "getattr()");
      const where = `${file}:${index + 1} ${line.trim()}`;
      const literals = [...value.matchAll(/(f?)(["'])(.*?)\2/g)];
      if (literals.some((match) => match[1] === "f" || match[3]!.includes("{")))
        unreviewed.push(`${where} (formats a code)`);
      // A code built from pieces cannot be looked up.
      if (/["']\s*[+%]|[+%]\s*["']|["']\s*\.(?:format|join)\(/.test(value))
        unreviewed.push(`${where} (builds a code)`);
      for (const match of literals)
        if (/^[a-z][a-z0-9_]*$/.test(match[3]!)) codes.add(match[3]!);
      if (PROPAGATED_LINES.has(line.trim())) return;
      // Every other name mixed into a code (`kind or "x"`, `CODES[kind]`,
      // `kind.lower()`, `else kind`, `error.code or kind`) can carry an
      // unmapped code. Only names reviewed against the service may appear:
      // the stored reason, the enabled check and phase, each assigned only
      // at literal sites.
      const names =
        value.replace(/(["']).*?\1/g, "").match(/[A-Za-z_]\w*/g) ?? [];
      const stray = names.filter((name) => !REVIEWED_NAMES.has(name));
      if (stray.length)
        unreviewed.push(`${where} (mixes in ${stray.join(", ")})`);
      else if (!literals.length && !/^\s*None\b/.test(value))
        unreviewed.push(where);
    });
    const safe =
      /safe_worker_codes\s*=\s*\{([^}]*)\}/.exec(lines.join("\n"))?.[1] ?? "";
    for (const match of safe.matchAll(/["']([a-z][a-z0-9_]*)["']/g))
      codes.add(match[1]!);
  }
  return { codes, unreviewed };
}

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
    const { codes, unreviewed } = sitesAndCodes();
    // Codes only a ternary, an `or` fallback or the router reach.
    for (const code of [
      "research_timeout",
      "provider_unavailable",
      "workspace_scope_changed",
      "not_enabled",
    ])
      expect(codes.has(code)).toBe(true);
    expect(unreviewed).toEqual([]);
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
