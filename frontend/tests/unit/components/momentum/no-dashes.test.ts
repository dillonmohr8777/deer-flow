import { readFileSync } from "node:fs";
import { readdir } from "node:fs/promises";
import { join } from "node:path";

import { describe, expect, it } from "@rstest/core";

/**
 * House style: no em or en dashes in anything a person reads. They are a tell
 * of unedited machine writing, which matters most on the surfaces that carry
 * the Momentum name. A colon, a comma, parentheses or two sentences all read
 * better than the dash did.
 *
 * Scope is deliberately the front door plus the invite and auth flows, which
 * is every surface a first-time visitor sees. Comments are exempt: this is a
 * rule about published copy, not about how the source explains itself.
 */

const ROOTS = [
  join(process.cwd(), "src", "components", "momentum"),
  join(process.cwd(), "src", "app", "invite"),
];

const DASHES = /[—–]/;

async function tsxFilesUnder(dir: string): Promise<string[]> {
  const entries = await readdir(dir, { withFileTypes: true });
  const found: string[] = [];
  for (const entry of entries) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) found.push(...(await tsxFilesUnder(path)));
    else if (entry.name.endsWith(".tsx")) found.push(path);
  }
  return found;
}

/** Strips // line comments and block comments so only real code/copy remains. */
function withoutComments(source: string) {
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
}

describe("published copy", () => {
  it("uses no em or en dashes on the front door, invite or auth surfaces", async () => {
    const files = (await Promise.all(ROOTS.map(tsxFilesUnder))).flat();
    expect(files.length).toBeGreaterThan(0);

    const offenders: string[] = [];
    for (const file of files) {
      const code = withoutComments(readFileSync(file, "utf8"));
      for (const [index, line] of code.split("\n").entries()) {
        if (DASHES.test(line)) {
          offenders.push(
            `${file.replace(process.cwd(), "")}:${index + 1} ${line.trim()}`,
          );
        }
      }
    }

    expect(offenders).toEqual([]);
  });
});
