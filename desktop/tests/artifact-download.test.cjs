"use strict";

const assert = require("node:assert/strict");
const { test } = require("node:test");
const { EventEmitter } = require("node:events");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { MAX_ARTIFACT_BYTES, artifactFilename, permittedArtifactDownload } = require("../src/security.cjs");
const { handleArtifactDownload } = require("../src/artifact-download.cjs");

const endpoint = "https://momo.example.com/workspace/openai";
const blobURL = "blob:https://momo.example.com/74cec975-0ffa-41b1-9c94-3fd90bba6f8d";
const artifactURL = `https://momo.example.com/api/openai-agents/sessions/${"a".repeat(32)}/artifacts/artifact_123/content`;
const candidate = { url: blobURL, urlChain: [blobURL], documentURL: endpoint, frameURL: endpoint, mimeType: "application/octet-stream", filename: "report.md", totalBytes: 7, receivedBytes: 0 };

class Item extends EventEmitter {
  constructor(overrides = {}) { super(); this.data = { ...candidate, gesture: true, ...overrides }; this.cancelled = false; }
  getURL() { return this.data.url; }
  getURLChain() { return this.data.urlChain; }
  getMimeType() { return this.data.mimeType; }
  getFilename() { return this.data.filename; }
  getTotalBytes() { return this.data.totalBytes; }
  getReceivedBytes() { return this.data.receivedBytes; }
  hasUserGesture() { return this.data.gesture; }
  setSavePath(value) { this.destination = value; }
  cancel() { this.cancelled = true; }
}

function setup(t, overrides = {}) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "momobot-download-test-"));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const event = { prevented: false, preventDefault() { this.prevented = true; } };
  const options = { endpoint, documentURL: endpoint, frameURL: endpoint, ownedFrame: true, downloadsDirectory: directory, confirm: () => false, ...overrides };
  return { event, options, directory };
}

test("only same-origin artifact routes and octet-stream blobs qualify", () => {
  assert.equal(permittedArtifactDownload(candidate, endpoint), true);
  assert.equal(permittedArtifactDownload({ ...candidate, url: artifactURL, urlChain: [artifactURL] }, endpoint), true);
  for (const url of ["https://evil.example/report.md", "https://momo.example.com/report.md", "https://momo.example.com.evil.example/", "data:text/plain,hello", "file:///tmp/report.md", "blob:https://evil.example/74cec975-0ffa-41b1-9c94-3fd90bba6f8d", "blob:https://user:password@momo.example.com/74cec975-0ffa-41b1-9c94-3fd90bba6f8d", `${artifactURL}?key=secret`, `${artifactURL}#token`]) assert.equal(permittedArtifactDownload({ ...candidate, url, urlChain: [url] }, endpoint), false);
  assert.equal(permittedArtifactDownload({ ...candidate, urlChain: ["https://evil.example/redirect", artifactURL] }, endpoint), false);
  for (const field of ["documentURL", "frameURL"]) assert.equal(permittedArtifactDownload({ ...candidate, [field]: "https://evil.example/frame" }, endpoint), false);
});

test("path traversal, executable extensions and unbounded metadata fail closed", () => {
  for (const filename of ["../report.md", "a\\report.md", ".hidden", "report.exe", "report.EXE.pdf", "run.command", "run.js", "file.dmg", "x\u0000.md", "report."]) assert.equal(artifactFilename(filename), null);
  assert.equal(artifactFilename("Agency report.html"), "Agency-report.html");
  for (const totalBytes of [MAX_ARTIFACT_BYTES + 1, -1, NaN, Infinity]) assert.equal(permittedArtifactDownload({ ...candidate, totalBytes }, endpoint), false);
  assert.equal(permittedArtifactDownload({ ...candidate, mimeType: "text/html" }, endpoint), false);
});

test("PNG screenshots and JSON evidence require matching safe filenames", () => {
  assert.equal(permittedArtifactDownload({ ...candidate, mimeType: "image/png", filename: "screenshot.png" }, endpoint), true);
  assert.equal(permittedArtifactDownload({ ...candidate, mimeType: "application/json", filename: "evidence.json" }, endpoint), true);
  assert.equal(permittedArtifactDownload({ ...candidate, mimeType: "image/png", filename: "screenshot.html" }, endpoint), false);
  assert.equal(permittedArtifactDownload({ ...candidate, mimeType: "application/json", filename: "evidence.js" }, endpoint), false);
});

test("deliberate download creates a unique private file and retains the complete artifact", (t) => {
  const results = [];
  const { event, options, directory } = setup(t, { confirm: () => assert.fail("A real user gesture does not need another prompt"), onResult: (result) => results.push(result) });
  fs.writeFileSync(path.join(directory, "report.md"), "original user file");
  const item = new Item();
  assert.equal(handleArtifactDownload(event, item, options), true);
  assert.equal(event.prevented, false);
  assert.equal(path.dirname(item.destination), directory);
  assert.notEqual(item.destination, path.join(directory, "report.md"));
  fs.writeFileSync(item.destination, "report");
  item.data.receivedBytes = 6;
  item.emit("done", {}, "completed");
  assert.equal(fs.readFileSync(item.destination, "utf8"), "report");
  assert.equal(fs.statSync(item.destination).mode & 0o777, 0o600);
  assert.equal(fs.readFileSync(path.join(directory, "report.md"), "utf8"), "original user file");
  assert.deepEqual(results, [{ saved: true, path: item.destination }]);
});

test("programmatic blob needs explicit confirmation and a foreign frame cannot download", (t) => {
  const { event, options, directory } = setup(t);
  assert.equal(handleArtifactDownload(event, new Item({ gesture: false }), options), false);
  assert.equal(event.prevented, true);
  assert.deepEqual(fs.readdirSync(directory), []);
  assert.equal(handleArtifactDownload(event, new Item(), { ...options, ownedFrame: false }), false);
  const accepted = new Item({ gesture: false });
  assert.equal(handleArtifactDownload({ preventDefault() { assert.fail("Explicit confirmation authorizes this file"); } }, accepted, { ...options, confirm: () => true }), true);
  accepted.emit("done", {}, "cancelled");
  assert.equal(fs.existsSync(accepted.destination), false);
});

test("unknown-size stream exceeding the cap is cancelled and its partial file removed", (t) => {
  const results = [];
  const { event, options } = setup(t, { onResult: (result) => results.push(result) });
  const item = new Item({ totalBytes: 0 });
  assert.equal(handleArtifactDownload(event, item, options), true);
  fs.writeFileSync(item.destination, "partial");
  item.data.receivedBytes = MAX_ARTIFACT_BYTES + 1;
  item.emit("updated", {}, "progressing");
  assert.equal(item.cancelled, true);
  item.emit("done", {}, "cancelled");
  assert.equal(fs.existsSync(item.destination), false);
  assert.deepEqual(results, [{ saved: false }]);
});

test("completed file size is independently bounded even when byte counters lie", (t) => {
  const { event, options } = setup(t);
  const item = new Item();
  assert.equal(handleArtifactDownload(event, item, options), true);
  fs.truncateSync(item.destination, MAX_ARTIFACT_BYTES + 1);
  item.emit("done", {}, "completed");
  assert.equal(fs.existsSync(item.destination), false);
});

test("interrupted downloads and invalid save directories leave no retained artifact", (t) => {
  const { event, options, directory } = setup(t);
  const item = new Item();
  assert.equal(handleArtifactDownload(event, item, options), true);
  item.emit("done", {}, "interrupted");
  assert.deepEqual(fs.readdirSync(directory), []);
  assert.equal(handleArtifactDownload(event, new Item(), { ...options, downloadsDirectory: "relative/path" }), false);
  assert.equal(event.prevented, true);
});
