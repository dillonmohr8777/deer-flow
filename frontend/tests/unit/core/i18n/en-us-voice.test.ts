import { describe, expect, it } from "@rstest/core";

import { enUS } from "@/core/i18n/locales/en-US";

const EM_DASH = "—"; // —
const EN_DASH = "–"; // –

// Functions in the locale (pluralized/interpolated copy) are inspected via
// their source text (`String(fn)`) instead of being invoked: the locale has
// dozens of them with differing arities and argument types, and a dash can
// only ever live in a function's static template/string-literal text, which
// the source text already contains in full. Calling each with bespoke
// plausible arguments would add risk (mismatched types, thrown errors) for
// no extra coverage. This mirrors the `pathsNaming` helper in the sibling
// product-name.test.ts, which uses the same `String(node)` technique.
function pathsWithDash(node: unknown, path = ""): string[] {
  if (typeof node === "string" || typeof node === "function") {
    const text = String(node);
    return text.includes(EM_DASH) || text.includes(EN_DASH) ? [path] : [];
  }
  if (node && typeof node === "object") {
    return Object.entries(node).flatMap(([key, value]) =>
      pathsWithDash(value, path ? `${path}.${key}` : key),
    );
  }
  return [];
}

describe("en-US voice: no dashes", () => {
  it("contains no em dash (—) or en dash (–) anywhere in the locale copy", () => {
    expect(pathsWithDash(enUS)).toEqual([]);
  });
});
