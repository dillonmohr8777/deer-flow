"use strict";

// Byte-scan a packaged app's Resources (our code, not upstream Electron binaries) for credential shapes.
const fs = require("node:fs");
const path = require("node:path");

const PATTERNS = {
  "openai-or-anthropic-key": /sk-(?:ant-|proj-)?[A-Za-z0-9_-]{24,}/u,
  "slack-token": /xox[abprs]-[A-Za-z0-9-]{10,}/u,
  "aws-access-key": /AKIA[0-9A-Z]{16}/u,
  "github-token": /gh[pousr]_[A-Za-z0-9]{36}/u,
  "google-api-key": /AIza[0-9A-Za-z_-]{35}/u,
  "private-key": /-----BEGIN [A-Z ]*PRIVATE KEY-----/u,
  "bearer-literal": /Bearer [A-Za-z0-9._-]{30,}/u,
};

/** @param {string} root @returns {{file:string, pattern:string}[]} */
function scanSecrets(root) {
  /** @type {{file:string, pattern:string}[]} */
  const hits = [];
  for (const entry of fs.readdirSync(root, { recursive: true, withFileTypes: true })) {
    if (!entry.isFile()) continue;
    const file = path.join(entry.parentPath, entry.name);
    const text = fs.readFileSync(file).toString("latin1");
    for (const [pattern, regex] of Object.entries(PATTERNS)) if (regex.test(text)) hits.push({ file: path.relative(root, file), pattern });
  }
  return hits;
}

module.exports = { scanSecrets };

if (require.main === module) {
  const target = process.argv[2];
  if (!target) throw new Error("usage: node scripts/scan-secrets.cjs <MomoBot.app>");
  const resources = path.join(target, "Contents/Resources");
  const hits = scanSecrets(fs.existsSync(resources) ? resources : target);
  // Print only file and pattern names, never the matched bytes.
  process.stdout.write(`${JSON.stringify({ type: "secret-scan", hits })}\n`);
  process.exitCode = hits.length ? 1 : 0;
}
