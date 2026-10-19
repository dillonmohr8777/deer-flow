"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { compareVersions, validateUpdateURL, checkForUpdate } = require("../src/update-check.cjs");

/** @param {number} status @param {unknown} body */
const serve = (status, body) => async () => ({ ok: status === 200, json: async () => body });

test("versions compare numerically, not as strings", () => {
  assert.ok(compareVersions("0.10.0", "0.9.9") > 0);
  assert.equal(compareVersions("0.3.0", "0.3.0"), 0);
  assert.ok(compareVersions("0.2.4", "0.3.0") < 0);
  assert.throws(() => compareVersions("0.3", "0.3.0"));
});

test("update URL must be plain HTTPS and gains a trailing slash", () => {
  assert.equal(validateUpdateURL("https://example.com/momobot"), "https://example.com/momobot/");
  assert.equal(validateUpdateURL("https://example.com"), "https://example.com/");
  for (const bad of ["http://example.com/", "https://user:pw@example.com/", "https://example.com/?x=1", "file:///tmp/", "", 42, undefined]) {
    assert.equal(validateUpdateURL(bad), undefined, String(bad));
  }
});

test("reports newer, current and unreachable", async () => {
  /** @type {string[]} */
  const fetched = [];
  const record = (/** @type {any} */ body) => async (/** @type {string} */ url) => { fetched.push(url); return { ok: true, json: async () => body }; };
  assert.deepEqual(await checkForUpdate({ updateURL: "https://example.com/r/", currentVersion: "0.3.0", fetchImpl: record({ product: "MomoBot", version: "0.3.1" }) }), { status: "newer", latest: "0.3.1" });
  assert.deepEqual(fetched, ["https://example.com/r/release.json"]);
  assert.deepEqual(await checkForUpdate({ updateURL: "https://example.com/", currentVersion: "0.3.0", fetchImpl: serve(200, { product: "MomoBot", version: "0.3.0" }) }), { status: "current", latest: "0.3.0" });
  assert.deepEqual(await checkForUpdate({ updateURL: "https://example.com/", currentVersion: "0.3.0", fetchImpl: serve(200, { product: "MomoBot", version: "0.2.9" }) }), { status: "current", latest: "0.2.9" });
  for (const fetchImpl of [serve(404, {}), serve(200, { product: "Other", version: "9.9.9" }), serve(200, { product: "MomoBot", version: "latest" }), async () => { throw new Error("offline"); }]) {
    assert.deepEqual(await checkForUpdate({ updateURL: "https://example.com/", currentVersion: "0.3.0", fetchImpl }), { status: "unreachable" });
  }
});
