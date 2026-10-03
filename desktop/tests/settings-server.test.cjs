"use strict";

const assert = require("node:assert/strict");
const { test } = require("node:test");
const http = require("node:http");
const { startSettingsServer } = require("../src/settings-server.cjs");

async function fixture(t) {
  const changes = [];
  const server = await startSettingsServer({ getEndpoint: () => "http://127.0.0.1:2030/workspace/openai", getFailure: () => "Offline", getExternal: () => "https://example.com", onConnect: async (value) => changes.push(value), onExternal: async () => changes.push("external"), onRetry: async () => changes.push("retry") });
  t.after(() => server.close());
  return { ...server, changes };
}

function request(origin, { method = "GET", path = "/", host, form, requestOrigin } = {}) {
  const headers = {};
  if (host) headers.Host = host;
  if (requestOrigin) headers.Origin = requestOrigin;
  if (form !== undefined) headers["Content-Type"] = "application/x-www-form-urlencoded";
  return new Promise((resolve, reject) => {
    const req = http.request(`${origin}${path}`, { method, headers }, (res) => {
      let body = "";
      res.on("data", (chunk) => { body += chunk; });
      res.on("end", () => resolve({ status: res.statusCode, headers: res.headers, body }));
    });
    req.on("error", reject);
    req.end(form);
  });
}

test("settings server blocks DNS rebinding hosts", async (t) => {
  const server = await fixture(t);
  const result = await request(server.origin, { host: "evil.example" });
  assert.equal(result.status, 403);
});

test("settings endpoint requires its origin and an unpredictable form nonce", async (t) => {
  const server = await fixture(t);
  const initial = await request(server.origin);
  assert.equal(initial.status, 200);
  assert.match(initial.headers["content-security-policy"], /default-src 'none'/u);
  assert.equal(initial.headers["cache-control"], "no-store");
  const nonce = /name="nonce" value="([a-f0-9]+)"/u.exec(initial.body)[1];
  for (const options of [{ requestOrigin: "https://evil.example", nonce }, { requestOrigin: server.origin, nonce: "wrong" }, { nonce }]) {
    const response = await request(server.origin, { method: "POST", path: "/connect", form: new URLSearchParams({ endpoint: "https://momo.example.com", nonce: options.nonce }).toString(), requestOrigin: options.requestOrigin });
    assert.equal(response.status, 403);
  }
  assert.deepEqual(server.changes, []);
  const response = await request(server.origin, { method: "POST", path: "/connect", form: new URLSearchParams({ endpoint: "https://momo.example.com", nonce }).toString(), requestOrigin: server.origin });
  assert.equal(response.status, 200);
  assert.deepEqual(server.changes, ["https://momo.example.com/workspace"]);
});

test("invalid configuration cannot redirect or reach native external opening", async (t) => {
  const server = await fixture(t);
  const initial = await request(server.origin);
  const nonce = /name="nonce" value="([a-f0-9]+)"/u.exec(initial.body)[1];
  const response = await request(server.origin, { method: "POST", path: "/connect", form: new URLSearchParams({ endpoint: "javascript:alert(1)", nonce }).toString(), requestOrigin: server.origin });
  assert.equal(response.status, 400);
  assert.deepEqual(server.changes, []);
  const external = await request(server.origin, { method: "POST", path: "/open-external", form: "nonce=wrong", requestOrigin: server.origin });
  assert.equal(external.status, 403);
  assert.deepEqual(server.changes, []);
});
