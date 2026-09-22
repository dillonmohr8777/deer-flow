import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "@rstest/core";

const root = join(__dirname, "../../..");

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sources(path);
    return /\.(tsx?|css)$/.test(name) ? [path] : [];
  });
}

describe("Momentum brand assets", () => {
  // The hero Momo shipped as a broken image because the component referenced
  // /momentum/momo-mark.svg while the file never reached this branch.
  it("every /momentum/ asset referenced from src exists in public", () => {
    const missing = new Set<string>();
    for (const file of sources(join(root, "src"))) {
      const text = readFileSync(file, "utf8");
      for (const [ref] of text.matchAll(
        /\/momentum\/[\w./-]+\.(?:svg|png|jpe?g|webp|woff2?|ttf)/g,
      )) {
        if (!existsSync(join(root, "public", ref))) missing.add(ref);
      }
    }
    expect([...missing]).toEqual([]);
  });
});
