import { describe, expect, it } from "@rstest/core";

import {
  composeIdentityPrompt,
  identityPromptChanged,
  identityVoiceIsValid,
  splitIdentityPrompt,
} from "@/components/workspace/agents/agent-identity-helpers";

describe("agent voice document preservation", () => {
  it("round-trips only its own trailing section without rewriting expert instructions", () => {
    const brief =
      "# Specialist\r\n\r\n## Voice\r\nAn existing section stays intact.  \r\n";
    expect(splitIdentityPrompt(brief)).toEqual({ brief, voice: "" });
    const combined = composeIdentityPrompt({
      brief,
      voice: "Warm and precise.",
    });
    const parsed = splitIdentityPrompt(combined);
    expect(parsed).toEqual({ brief, voice: "Warm and precise." });
    expect(identityPromptChanged(combined, parsed)).toBe(false);
    expect(composeIdentityPrompt({ ...parsed, voice: "" })).toBe(brief);
    expect(
      splitIdentityPrompt(`${combined}\nExtra expert instruction.`),
    ).toEqual({ brief: `${combined}\nExtra expert instruction.`, voice: "" });
    expect(identityVoiceIsValid("🦌".repeat(1600))).toBe(true);
    expect(identityVoiceIsValid("🦌".repeat(1601))).toBe(false);
    expect(identityVoiceIsValid("<!-- /momentum:voice -->")).toBe(false);
  });
});
