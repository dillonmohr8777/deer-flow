import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "@rstest/core";

// Owner decision 2026-09-22: brand tokens only, no AI purple on the primary
// action or the lead-agent card. Reads the real stylesheet.
const css = readFileSync(
  join(
    __dirname,
    "..",
    "..",
    "src",
    "components",
    "workspace",
    "command-center",
    "command-center.module.css",
  ),
  "utf8",
);

function rule(selector: string): string {
  const start = css.indexOf(`\n${selector} {`);
  expect(start).toBeGreaterThan(-1);
  return css.slice(start, css.indexOf("}", start));
}

describe("command center brand surfaces", () => {
  for (const selector of [
    ".primary",
    ".primary:hover",
    ".topologyLead",
    ".topologyLead::after",
  ]) {
    it(`${selector} is a flat brand fill, not a violet gradient`, () => {
      const body = rule(selector);
      expect(body).not.toMatch(/gradient/);
      expect(body).not.toMatch(/#5b3bd8|#4c2fc3|#4d35c6|--violet/i);
    });
  }
});
