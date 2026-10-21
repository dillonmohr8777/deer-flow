"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { scanSecrets } = require("../scripts/scan-secrets.cjs");

test("secret scan flags planted credential shapes and passes clean bundles", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "momobot-scan-"));
  fs.mkdirSync(path.join(root, "app"));
  fs.writeFileSync(path.join(root, "app/clean.js"), "const endpoint = 'https://example.test/workspace';\n");
  assert.deepEqual(scanSecrets(root), []);
  fs.writeFileSync(path.join(root, "app/leak.js"), `const key = "sk-${"a".repeat(30)}";\n`);
  assert.deepEqual(scanSecrets(root), [{ file: path.join("app", "leak.js"), pattern: "openai-or-anthropic-key" }]);
  fs.rmSync(root, { recursive: true });
});
