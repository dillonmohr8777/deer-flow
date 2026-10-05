"use strict";
const assert = require("node:assert/strict");
const { test } = require("node:test");
const { releaseSigning, notaryAuthArgs, publicReleaseMetadata } = require("../src/release-config.cjs");

test("local build defaults to ad-hoc without notarization credentials", () => {
  assert.equal(releaseSigning({}).mode, "ad-hoc");
});

test("distribution refuses partial, empty, non Developer ID, or malformed configuration", () => {
  for (const value of [
    { MOMOBOT_SIGNING_IDENTITY: "Developer ID Application: Example (TEAM)" },
    { MOMOBOT_NOTARY_PROFILE: "existing-profile" },
    { MOMOBOT_SIGNING_IDENTITY: "", MOMOBOT_NOTARY_PROFILE: "" },
    { MOMOBOT_SIGNING_IDENTITY: "Apple Development: Example", MOMOBOT_NOTARY_PROFILE: "existing" },
    { MOMOBOT_SIGNING_IDENTITY: "Developer ID Application: Example", MOMOBOT_NOTARY_PROFILE: "existing\n" },
  ]) assert.throws(() => releaseSigning(value));
  assert.equal(releaseSigning({ MOMOBOT_SIGNING_IDENTITY: "Developer ID Application: Example (TEAM)", MOMOBOT_NOTARY_PROFILE: "existing-profile" }).mode, "developer-id");
});

test("public metadata admits only fixed filenames and full source/checksum digests", () => {
  const input = { version: "0.2.0", electron: "44.5.0", revision: "a".repeat(40), dirty: false, signing: "ad-hoc", builtAt: "2026-10-03T00:00:00Z", checksums: { "MomoBot-mac-arm64.zip": "b".repeat(64) } };
  const metadata = publicReleaseMetadata(input);
  assert.deepEqual(metadata.artifacts, [{ filename: "MomoBot-mac-arm64.zip", sha256: "b".repeat(64) }]);
  assert.equal(JSON.stringify(metadata).includes("/Users/"), false);
  assert.throws(() => publicReleaseMetadata({ ...input, revision: "short" }));
  assert.throws(() => publicReleaseMetadata({ ...input, checksums: { "/Users/private.zip": "b".repeat(64) } }));
  assert.throws(() => publicReleaseMetadata({ ...input, checksums: { "MomoBot-mac-arm64.zip": "bad" } }));
});

const ID = "Developer ID Application: Example (TEAM)";
const API = { APPLE_API_KEY: "/tmp/AuthKey_ABC.p8", APPLE_API_KEY_ID: "ABC", APPLE_API_ISSUER: "uuid" };

test("API key route needs identity plus all three variables and excludes a profile", () => {
  const s = releaseSigning({ MOMOBOT_SIGNING_IDENTITY: ID, ...API });
  assert.equal(s.mode, "developer-id");
  assert.deepEqual(notaryAuthArgs(s), ["--key", "/tmp/AuthKey_ABC.p8", "--key-id", "ABC", "--issuer", "uuid"]);
  assert.throws(() => releaseSigning({ ...API }));
  assert.throws(() => releaseSigning({ MOMOBOT_SIGNING_IDENTITY: ID, APPLE_API_KEY: API.APPLE_API_KEY }));
  assert.throws(() => releaseSigning({ MOMOBOT_SIGNING_IDENTITY: ID, ...API, APPLE_API_KEY: "relative.p8" }));
  assert.throws(() => releaseSigning({ MOMOBOT_SIGNING_IDENTITY: ID, ...API, MOMOBOT_NOTARY_PROFILE: "p" }));
  assert.deepEqual(notaryAuthArgs(releaseSigning({ MOMOBOT_SIGNING_IDENTITY: ID, MOMOBOT_NOTARY_PROFILE: "p" })), ["--keychain-profile", "p"]);
  assert.throws(() => notaryAuthArgs(releaseSigning({})));
});

test("entitlements stay minimal", () => {
  const plist = require("node:fs").readFileSync(require("node:path").join(__dirname, "../build/entitlements.mac.plist"), "utf8");
  const keys = [...plist.matchAll(/<key>([^<]+)<\/key>/gu)].map((m) => m[1]).sort();
  assert.deepEqual(keys, ["com.apple.security.cs.allow-jit", "com.apple.security.cs.allow-unsigned-executable-memory", "com.apple.security.device.audio-input"]);
});
