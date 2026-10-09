import { expect, it } from "@rstest/core";

import { getPluginStatus } from "@/components/workspace/capabilities/plugin-status";
import { capabilityCopy } from "@/core/capabilities/copy";
import type { CapabilityInstallation } from "@/core/capabilities/types";
import { enUS } from "@/core/i18n/locales/en-US";

const labels = capabilityCopy("en-US");

function installed(auth_status: string): CapabilityInstallation {
  return { auth_status } as unknown as CapabilityInstallation;
}

it("says a failed status read is unavailable, not unconfigured", () => {
  expect(getPluginStatus("mcp", undefined, true, enUS, labels)).toEqual({
    label: "Integration status unavailable",
    tone: "unknown",
  });
  // Even an installed row: an errored read cannot vouch for it.
  expect(
    getPluginStatus("mcp", installed("connected"), true, enUS, labels).tone,
  ).toBe("unknown");
});

it("keeps ok for real installations and flags a missing account", () => {
  expect(
    getPluginStatus("mcp", installed("connected"), false, enUS, labels),
  ).toEqual({ label: "Account connected", tone: "ok" });
  expect(
    getPluginStatus("mcp", installed("configured"), false, enUS, labels).tone,
  ).toBe("ok");
  expect(
    getPluginStatus("mcp", installed("required"), false, enUS, labels),
  ).toEqual({ label: "Account required", tone: "attention" });
});

it("leaves uninstalled entries idle with their own wording", () => {
  expect(getPluginStatus("guide", undefined, false, enUS, labels)).toEqual({
    label: enUS.capabilities.directory.candidate,
    tone: "idle",
  });
  expect(getPluginStatus("lark", undefined, false, enUS, labels).label).toBe(
    "Not installed",
  );
  expect(getPluginStatus("mcp", undefined, false, enUS, labels)).toEqual({
    label: "Not configured",
    tone: "idle",
  });
});
