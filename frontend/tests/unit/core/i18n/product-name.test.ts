import { describe, expect, it } from "@rstest/core";

import { enUS } from "@/core/i18n/locales/en-US";
import { zhCN } from "@/core/i18n/locales/zh-CN";

// The product is MomoBot (by Momentum). "DeerFlow" may only name the upstream project,
// in the menu entries that link to its site, repository and About page.
const UPSTREAM_LINKS = [
  "workspace.about",
  "workspace.githubTooltip",
  "workspace.officialWebsite",
  "workspace.visitGithub",
];

function pathsNaming(node: unknown, name: string, path = ""): string[] {
  if (typeof node === "string" || typeof node === "function") {
    return String(node).includes(name) ? [path] : [];
  }
  if (node && typeof node === "object") {
    return Object.entries(node).flatMap(([key, value]) =>
      pathsNaming(value, name, path ? `${path}.${key}` : key),
    );
  }
  return [];
}

describe("product name in locale copy", () => {
  for (const [locale, copy] of [
    ["en-US", enUS],
    ["zh-CN", zhCN],
  ] as const) {
    it(`${locale} names DeerFlow only on upstream links`, () => {
      expect(pathsNaming(copy, "DeerFlow").sort()).toEqual(UPSTREAM_LINKS);
    });
  }
});
