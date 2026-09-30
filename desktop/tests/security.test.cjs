"use strict";

const assert = require("node:assert/strict");
const { test } = require("node:test");
const { validateEndpoint, isSameOriginNavigation, safeExternalURL, permittedMediaRequest, rendererPreferences } = require("../src/security.cjs");

test("remote URLs require HTTPS and localhost is the only HTTP exception", () => {
  assert.equal(validateEndpoint("https://momo.example.com"), "https://momo.example.com/workspace/openai");
  assert.equal(validateEndpoint("http://127.0.0.1:2030/workspace/openai"), "http://127.0.0.1:2030/workspace/openai");
  assert.equal(validateEndpoint("http://[::1]:2030"), "http://[::1]:2030/workspace/openai");
  for (const url of ["http://momo.example.com", "http://192.168.1.5:2030", "http://127.0.0.1.evil.example", "http://localhost.evil.example", "file:///etc/passwd", "javascript:alert(1)", "data:text/html,hello"]) assert.throws(() => validateEndpoint(url));
});

test("connection settings reject embedded credentials and accidental secrets", () => {
  for (const url of ["https://user:password@momo.example.com", "https://momo.example.com?api_key=secret", "https://momo.example.com#token", "https://momo.example.com\\@evil.example", "https://momo.example.com\n"]) assert.throws(() => validateEndpoint(url));
});

test("workspace navigation is restricted by parsed exact origin", () => {
  const endpoint = "https://momo.example.com/workspace/openai";
  assert.equal(isSameOriginNavigation("https://momo.example.com/api/v1/auth/login", endpoint, "http://127.0.0.1:50000"), true);
  assert.equal(isSameOriginNavigation("http://127.0.0.1:50000/error", endpoint, "http://127.0.0.1:50000"), true);
  for (const url of ["https://momo.example.com.evil.example", "https://momo.example.com:444", "http://momo.example.com", "https://user@momo.example.com", "file:///etc/passwd"]) assert.equal(isSameOriginNavigation(url, endpoint, "http://127.0.0.1:50000"), false);
});

test("external confirmation never passes shell protocols or HTTP to the OS", () => {
  assert.equal(safeExternalURL("https://example.com/report"), "https://example.com/report");
  for (const url of ["javascript:alert(1)", "file:///Applications/Terminal.app", "smb://example.com", "mailto:person@example.com", "http://example.com", "https://user:password@example.com", "https://localhost/private", null]) assert.equal(safeExternalURL(url), null);
});

test("only same-origin audio permission is available; camera and unknown permissions fail closed", () => {
  const endpoint = "https://momo.example.com/workspace/openai";
  assert.equal(permittedMediaRequest("media", "https://momo.example.com", endpoint, { mediaTypes: ["audio"] }), true);
  assert.equal(permittedMediaRequest("media", "https://momo.example.com", endpoint, { mediaType: "audio" }), true);
  for (const [permission, origin, details] of [["notifications", "https://momo.example.com", {}], ["media", "https://evil.example", { mediaTypes: ["audio"] }], ["media", "https://momo.example.com", { mediaTypes: ["audio", "video"] }], ["media", "https://momo.example.com", {}]]) assert.equal(permittedMediaRequest(permission, origin, endpoint, details), false);
});

test("renderer has no native execution or relaxed web security", () => {
  const preferences = rendererPreferences();
  for (const name of ["nodeIntegration", "nodeIntegrationInWorker", "nodeIntegrationInSubFrames", "allowRunningInsecureContent", "webviewTag"]) assert.equal(preferences[name], false);
  for (const name of ["contextIsolation", "sandbox", "webSecurity"]) assert.equal(preferences[name], true);
  assert.equal("preload" in preferences, false);
  assert.equal(preferences.partition.startsWith("persist:"), true);
});
