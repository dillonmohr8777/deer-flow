import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "@rstest/core";

import {
  CREW_GENERIC,
  CREW_MESSAGES,
  crewAuthor,
  crewState,
  crewWords,
  specialistNumbers,
} from "@/components/workspace/openai-crew-words";

const GATEWAY = resolve(__dirname, "../../../../../backend/app/gateway");
const SOURCES = [
  resolve(GATEWAY, "openai_agent_service.py"),
  resolve(GATEWAY, "routers/openai_agents.py"),
];

// Every place a code is raised or stored: the exception, last_error through
// the "unknown" storage action, the status reason, and the router's detail.
const SITE =
  /AgentServiceError\(|_storage\("unknown"|\breason\s*=|\bdetail\s*=/;
// Lines allowed to pass a code on through a name, each passing on a code
// raised at a literal site. A new propagation line must be reviewed here.
const PROPAGATED_LINES = new Set([
  "raise HTTPException(error.status_code, detail=error.code) from None",
]);

function sitesAndCodes() {
  const codes = new Set<string>();
  const unreviewed: string[] = [];
  for (const file of SOURCES) {
    readFileSync(file, "utf-8")
      .split("\n")
      .forEach((line, index) => {
        const site = SITE.exec(line);
        if (!site || /^\s*(?:#|class |def )/.test(line)) return;
        if (PROPAGATED_LINES.has(line.trim())) return;
        // Subscripts (`row["owner"]`) are keys, not codes.
        const value = line
          .slice(site.index)
          .replace(/\[\s*["'][^"']*["']\s*\]/g, "[key]");
        const literals = [...value.matchAll(/(["'])(.*?)\1/g)].map(
          (match) => match[2]!,
        );
        // The storage action's own name is not a stored code.
        const stored = line.includes('_storage("unknown"')
          ? literals.slice(1)
          : literals;
        const found = stored.filter((text) => /^[a-z][a-z0-9_]*$/.test(text));
        if (!found.length && !stored.some((text) => text.includes(" ")))
          unreviewed.push(`${file}:${index + 1} ${line.trim()}`);
        found.forEach((code) => codes.add(code));
      });
  }
  return { codes, unreviewed };
}

describe("crewWords", () => {
  it("gives a code its sentence and never shows a raw code", () => {
    expect(crewWords("missing_api_key")).toBe(
      "OpenAI is not connected on this server. An admin adds the API key.",
    );
    expect(crewWords(new Error("provider_outcome_unknown"))).toMatch(
      /^OpenAI did not confirm what happened/,
    );
    expect(crewWords("some_new_code")).toBe(CREW_GENERIC);
    expect(crewWords("OpenAI agent request failed")).toBe(CREW_GENERIC);
    expect(crewWords(null)).toBe(CREW_GENERIC);
  });

  it("passes a sentence through", () => {
    expect(crewWords("Authentication required")).toBe(
      "Authentication required",
    );
  });

  it("has words for every code the service raises or stores", () => {
    const { codes, unreviewed } = sitesAndCodes();
    // Codes only a ternary, the storage action or the router reach.
    for (const code of [
      "missing_api_key",
      "sdk_upgrade_required",
      "deadline_cancel_outcome_unknown",
      "workspace_scope_changed",
      "hosted_browser_disabled_pending_action_policy",
    ])
      expect(codes.has(code)).toBe(true);
    expect(unreviewed).toEqual([]);
    expect([...codes].filter((code) => !CREW_MESSAGES[code])).toEqual([]);
  });
});

describe("crewState", () => {
  it("uses the board's words: only running work is Working", () => {
    expect(crewState("in_progress")).toEqual({
      label: "Working",
      tone: "active",
    });
    expect(crewState("queued").label).toBe("Queued");
    expect(crewState("completed")).toEqual({ label: "Done", tone: "ok" });
    expect(crewState("failed").tone).toBe("danger");
    expect(crewState("unknown")).toEqual({
      label: "Unconfirmed",
      tone: "attention",
    });
    expect(crewState("idle").label).toBe("Ready");
    expect(crewState("something_new").label).toBe("Unknown");
  });
});

describe("crewAuthor", () => {
  it("names specialists by number, never by provider id", () => {
    const items = [
      { type: "message", role: "user", subagent_id: null },
      { type: "create_subagent_call", role: null, subagent_id: "sa_9" },
      {
        type: "agent_message",
        role: "assistant",
        subagent_id: "sa_9",
        phase: "final_answer",
      },
      { type: "agent_message", role: "assistant", subagent_id: "sa_2" },
      { type: "message", role: "assistant", subagent_id: null },
    ];
    const numbers = specialistNumbers(items);
    expect(items.map((item) => crewAuthor(item, numbers))).toEqual([
      "You",
      "MomoBot, to specialist 1",
      "Specialist 1, final answer",
      "Specialist 2",
      "MomoBot",
    ]);
  });
});
