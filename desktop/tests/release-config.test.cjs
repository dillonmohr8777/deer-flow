"use strict";
const assert = require("node:assert/strict");
const { test } = require("node:test");
const { releaseSigning, publicReleaseMetadata } = require("../src/release-config.cjs");

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
