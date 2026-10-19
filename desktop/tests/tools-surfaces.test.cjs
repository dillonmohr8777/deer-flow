"use strict";

const assert = require("node:assert/strict");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");
const { test } = require("node:test");
process.env.MOMOBOT_TOOLS_HOME = fs.mkdtempSync(path.join(os.tmpdir(), "momobot-tools-surface-"));
const { startSettingsServer, SECRET_HEADER } = require("../src/settings-server.cjs");
let secret = "";
const tools = require("../src/tools/tools.cjs");

function post(origin, path_, form) {
  return new Promise((resolve, reject) => {
    const req = http.request(`${origin}${path_}`, { method: "POST", headers: { [SECRET_HEADER]: secret, Origin: origin, "Content-Type": "application/x-www-form-urlencoded" } }, (res) => {
      let body = ""; res.on("data", (c) => { body += c; }); res.on("end", () => resolve({ status: res.statusCode, body }));
    });
    req.on("error", reject); req.end(form);
  });
}
const get = (origin, path_) => new Promise((resolve, reject) => http.get(`${origin}${path_}`, { headers: { [SECRET_HEADER]: secret } }, (res) => { let b = ""; res.on("data", (c) => { b += c; }); res.on("end", () => resolve({ status: res.statusCode, body: b })); }).on("error", reject));

test("Tools panel lists every tool, and only runs one with the page's form token", async (t) => {
  const server = await startSettingsServer({ tools, getEndpoint: () => "http://127.0.0.1:2030/workspace", getFailure: () => "", getExternal: () => undefined, onConnect: async () => {}, onExternal: async () => {}, onRetry: async () => {} });
  t.after(() => server.close());
  secret = server.secret;
  const panel = await get(server.origin, "/tools");
  assert.equal(panel.status, 200);
  for (const tool of tools.TOOLS) assert.match(panel.body, new RegExp(`Run ${tool.name}`));
  const nonce = /name="nonce" value="([0-9a-f]+)"/u.exec(panel.body)[1];
  assert.equal((await post(server.origin, "/tools/run", "tool=browse_snapshot&f_session=nope")).status, 403);
  const ran = await post(server.origin, "/tools/run", `nonce=${nonce}&tool=browse_snapshot&f_session=nope`);
  assert.equal(ran.status, 200);
  assert.match(ran.body, /no browser session nope/u);
  const refused = await post(server.origin, "/tools/run", `nonce=${nonce}&tool=fetch_page&f_url=${encodeURIComponent("http://127.0.0.1:8001/secret")}`);
  assert.match(refused.body, /public http\(s\) pages only/u);
  assert.equal((await get(server.origin, "/tools/shot/..%2F..%2Fetc%2Fpasswd")).status, 404);
});

test("MCP server speaks JSON-RPC over stdio: initialize, list the tools, return a tool error as a result", async () => {
  const child = spawn(process.execPath, [path.join(__dirname, "../src/tools/mcp-server.cjs")], { stdio: ["pipe", "pipe", "inherit"], env: process.env });
  const lines = [];
  let buffer = "";
  child.stdout.on("data", (chunk) => { buffer += chunk; const parts = buffer.split("\n"); buffer = parts.pop(); lines.push(...parts.filter(Boolean).map((l) => JSON.parse(l))); });
  const ask = async (id, method, params) => {
    child.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", id, method, params })}\n`);
    for (let i = 0; i < 100; i++) { const hit = lines.find((l) => l.id === id); if (hit) return hit; await new Promise((r) => setTimeout(r, 50)); }
    throw new Error("no reply");
  };
  try {
    assert.equal((await ask(1, "initialize", { protocolVersion: "2025-06-18" })).result.serverInfo.name, "momobot-desktop-tools");
    const listed = (await ask(2, "tools/list")).result.tools;
    assert.deepEqual(listed.map((x) => x.name), tools.TOOLS.map((x) => x.name));
    assert.deepEqual(listed.find((x) => x.name === "vault_login_with").inputSchema.required, ["session", "id"]);
    const called = (await ask(3, "tools/call", { name: "browse_click", arguments: { session: "zzz", ref: 1 } })).result;
    assert.equal(called.isError, true);
    assert.match(called.content[0].text, /no browser session zzz/u);
    assert.equal((await ask(4, "bogus")).error.code, -32601);
  } finally { child.stdin.end(); }
});

test("no tool takes a password, token or code as input, so secrets cannot be supplied through an agent call", () => {
  for (const tool of tools.TOOLS) for (const key of Object.keys(tool.input)) assert.doesNotMatch(key, /pass(word)?$|secret|token|totp$|^code$/iu, `${tool.name}.${key}`);
});
