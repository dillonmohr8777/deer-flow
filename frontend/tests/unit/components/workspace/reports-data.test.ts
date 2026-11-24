import { describe, expect, it } from "@rstest/core";

import {
  connectorStatusMeta,
  dataStateMeta,
  formatLeadCount,
  matchStatusMeta,
  reviewStatusMeta,
  validateGoogleDocUrlClient,
} from "@/components/workspace/reports/reports-data";

describe("reports-data helpers", () => {
  it("formats integer lead counts and never turns pending or unavailable feeds into 0", () => {
    expect(formatLeadCount(0, "verified")).toBe("0");
    expect(formatLeadCount(1240, "verified")).toBe("1,240");
    expect(formatLeadCount(null, "pending")).toBe("Pending");
    expect(formatLeadCount(undefined, "pending")).toBe("Pending");
    expect(formatLeadCount(null, "unavailable")).toBe("Unavailable");
    // Non-integer float values are refused and never displayed as verified counts.
    expect(formatLeadCount(12.5, "pending")).toBe("Pending");
  });

  it("maps connector, data, match-back, and review statuses to semantic tones", () => {
    expect(connectorStatusMeta("connected")).toEqual({
      label: "Connected",
      tone: "ok",
    });
    expect(connectorStatusMeta("stale")).toEqual({
      label: "Stale",
      tone: "attention",
    });
    expect(connectorStatusMeta("pending")).toEqual({
      label: "Pending",
      tone: "idle",
    });
    expect(connectorStatusMeta("unavailable")).toEqual({
      label: "Unavailable",
      tone: "danger",
    });

    expect(dataStateMeta("verified").tone).toBe("ok");
    expect(dataStateMeta("partial").tone).toBe("attention");
    expect(dataStateMeta("pending").tone).toBe("idle");
    expect(dataStateMeta("unavailable").tone).toBe("danger");

    expect(matchStatusMeta("matched").tone).toBe("ok");
    expect(matchStatusMeta("unmatched").tone).toBe("danger");
    expect(matchStatusMeta("pending_verification").tone).toBe("attention");

    expect(reviewStatusMeta("pending_review").tone).toBe("attention");
    expect(reviewStatusMeta("approved").tone).toBe("ok");
    expect(reviewStatusMeta("needs_edits").tone).toBe("danger");
  });

  it("validates Google Doc and Drive HTTPS URLs strictly", () => {
    expect(
      validateGoogleDocUrlClient(
        "https://docs.google.com/document/d/synthetic-doc-001/edit",
      ),
    ).toBeNull();
    expect(
      validateGoogleDocUrlClient(
        "https://drive.google.com/file/d/synthetic-file-002/view",
      ),
    ).toBeNull();

    expect(validateGoogleDocUrlClient("")).not.toBeNull();
    expect(
      validateGoogleDocUrlClient("http://docs.google.com/document/d/insecure"),
    ).not.toBeNull();
    expect(
      validateGoogleDocUrlClient("https://example.invalid/document/d/123"),
    ).not.toBeNull();
    expect(validateGoogleDocUrlClient("javascript:alert(1)")).not.toBeNull();
    expect(
      validateGoogleDocUrlClient("https://docs.google.com/"),
    ).not.toBeNull();
  });
});
