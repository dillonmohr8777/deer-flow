import { describe, expect, it } from "@rstest/core";

import {
  parseConnectHint,
  reasonText,
  retryText,
  sameToolkit,
} from "@/core/integrations/composio/api";

describe("composio connect helpers", () => {
  it("reads only a well-formed connect request from a tool result", () => {
    const body = {
      status: "no_connected_account",
      no_execution: true,
      connect: { handle: "h_0123456789abcdef", toolkit: "gmail" },
    };
    expect(parseConnectHint(JSON.stringify(body))).toEqual({
      handle: "h_0123456789abcdef",
      toolkit: "gmail",
    });
    // MCP text blocks may wrap the JSON in prose.
    expect(parseConnectHint(`result: ${JSON.stringify(body)}`)?.toolkit).toBe(
      "gmail",
    );
    expect(parseConnectHint("all good")).toBeNull();
    expect(
      parseConnectHint(
        JSON.stringify({
          ...body,
          connect: { handle: "../x", toolkit: "gmail" },
        }),
      ),
    ).toBeNull();
    expect(
      parseConnectHint(JSON.stringify({ ...body, status: "ok" })),
    ).toBeNull();
  });

  it("explains every held state in plain words", () => {
    expect(reasonText("owner_setup_required")).toMatch(/workspace owner/);
    expect(reasonText("something_new")).toBe("Not available yet.");
    expect(reasonText(null)).toBe("");
    expect(retryText({ state: "not_requested" })).toBe("Connected.");
    expect(retryText({ state: "submitted", run_id: "r" })).toMatch(/finishing/);
    expect(
      retryText({ state: "held", reason: "retry_admission_unavailable" }),
    ).toMatch(/on hold/);
  });

  it("matches toolkit ids across spellings", () => {
    expect(sameToolkit("google_calendar", "googlecalendar")).toBe(true);
    expect(sameToolkit("gmail", "googledrive")).toBe(false);
  });
});
