import { expect, it } from "@rstest/core";

import { getPluginAction } from "@/components/workspace/capabilities/plugin-action";
import type { CapabilityInstallation } from "@/core/capabilities/types";

function installed(auth_status: string): CapabilityInstallation {
  return { auth_status } as unknown as CapabilityInstallation;
}

it("asks for Connect only where an account flow applies", () => {
  expect(getPluginAction("mcp", installed("required"), false)).toBe("connect");
  expect(getPluginAction("mcp", installed("required"), true)).toBe("connect");
  expect(getPluginAction("lark", undefined, true)).toBe("connect");
});

it("offers Configure only to someone who can change the settings", () => {
  expect(getPluginAction("business", undefined, true)).toBe("configure");
  expect(getPluginAction("mcp", installed("configured"), true)).toBe(
    "configure",
  );
  expect(getPluginAction("business", undefined, false)).toBe("details");
  expect(getPluginAction("lark", undefined, false)).toBe("details");
  expect(getPluginAction("mcp", installed("connected"), false)).toBe("details");
});

it("names a setup reference as a guide, never Configure", () => {
  expect(getPluginAction("guide", undefined, true)).toBe("guide");
  expect(getPluginAction("guide", undefined, false)).toBe("guide");
});
