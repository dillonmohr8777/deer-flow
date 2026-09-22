/*
 * WCAG contrast check for the paper cutout treatment.
 *
 * Tokens are read straight out of src/styles/paper.css (the
 * [data-treatment="paper"] block) rather than restated here, so a printed
 * ratio can never drift from the value that actually ships. Same rule as
 * Bridge's scripts/check-contrast-suite-peek.mjs.
 *
 *   node scripts/check-paper-contrast.mjs
 *
 * Prints every text/surface pairing in the treatment with its computed
 * ratio, plus the two OBJECT-ONLY accent colours (--paper-brass,
 * --paper-cyan) which are expected to fail text contrast — they are never
 * used as a text colour, only as hardware (pin, deckle line accents). Their
 * -text variants (--paper-brass-text, --paper-cyan-text) are the ones
 * checked as text.
 *
 * Exit 1 if any TEXT or UI pairing fails its threshold. Object-only pairs
 * never affect the exit code.
 */
import { readFileSync } from "node:fs";

const css = readFileSync(
  new URL("../src/styles/paper.css", import.meta.url),
  "utf8",
);

const block = css.slice(
  css.indexOf('[data-treatment="paper"] {'),
  css.indexOf("\n}", css.indexOf('[data-treatment="paper"] {')),
);
const tokens = Object.fromEntries(
  [...block.matchAll(/(--paper-[a-z-]+):\s*(#[0-9a-fA-F]{3,8})\s*;/g)].map(
    (m) => [m[1], m[2]],
  ),
);
if (Object.keys(tokens).length === 0) {
  throw new Error("no --paper-* tokens found in paper.css — parse broke");
}

function hex(value) {
  const t = value.startsWith("--") ? tokens[value] : value;
  if (!t) throw new Error(`no value for ${value}`);
  let h = t.replace("#", "");
  if (h.length === 3) h = [...h].map((c) => c + c).join("");
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
}

const ch = (v) => {
  const s = v / 255;
  return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
};
const lum = (c) => 0.2126 * ch(c[0]) + 0.7152 * ch(c[1]) + 0.0722 * ch(c[2]);
const ratio = (a, b) => {
  const [x, y] = [lum(hex(a)), lum(hex(b))].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
};

/* [label, fg, bg, threshold] — threshold 4.5 = text, 3 = UI-only component. */
const pairs = [
  ["ink on cream", "--paper-ink", "--paper-cream", 4.5],
  ["ink on cream-hi", "--paper-ink", "--paper-cream-hi", 4.5],
  ["ink-muted on cream-hi (secondary text on card)", "--paper-ink-muted", "--paper-cream-hi", 4.5],
  ["kraft on ink (label chip)", "--paper-kraft", "--paper-ink", 4.5],
  ["royal on cream", "--paper-royal", "--paper-cream", 4.5],
  ["cream on royal-deep (inverse text on filled surface)", "--paper-cream", "--paper-royal-deep", 4.5],
  ["ink-muted on cream", "--paper-ink-muted", "--paper-cream", 4.5],
  ["brass-text on cream", "--paper-brass-text", "--paper-cream", 4.5],
  ["cyan-text on cream", "--paper-cyan-text", "--paper-cream", 4.5],
  ["line on cream (UI only, border/rule)", "--paper-line", "--paper-cream", 3],
  ["focus on cream", "--paper-focus", "--paper-cream", 4.5],
  ["danger on cream", "--paper-danger", "--paper-cream", 4.5],
  ["ok on cream", "--paper-ok", "--paper-cream", 4.5],
];

const objectOnly = [
  ["brass on cream (object-only — pin/rivet, never text)", "--paper-brass", "--paper-cream"],
  ["cyan on cream (object-only — never text)", "--paper-cyan", "--paper-cream"],
];

let failed = 0;
console.log("Paper cutout treatment — WCAG contrast, tokens read from src/styles/paper.css\n");
for (const [name, fg, bg, need] of pairs) {
  const r = ratio(fg, bg);
  const ok = r >= need;
  if (!ok) failed += 1;
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${r.toFixed(2).padStart(5)}:1  (needs ${need}:1)  ${name}`);
}
console.log(`\n${pairs.length - failed}/${pairs.length} text/UI pairs pass\n`);

console.log("Object-only accents (expected to fail text contrast — never used as text):");
for (const [name, fg, bg] of objectOnly) {
  const r = ratio(fg, bg);
  console.log(`  OBJECT-ONLY  ${r.toFixed(2).padStart(5)}:1  ${name}`);
}

process.exit(failed ? 1 : 0);
