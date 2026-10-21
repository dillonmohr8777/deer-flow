"use strict";
const { test, mock } = require("node:test");
const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const path = require("node:path");
const browse = require("../src/tools/browse.cjs");
let vaultReads = 0;
mock.method(require("node:child_process"), "execFile", (_file, _args, _options, callback) => {
  vaultReads++;
  callback(null, JSON.stringify({ login: { username: "synthetic-user", password: "synthetic-password", uris: [{ uri: "https://example.com" }] } }));
});
const vault = require("../src/tools/vault.cjs");
const { acceptanceFailures } = require("../scripts/tools-acceptance.cjs");

test("cloud click and every key fail before any browser input, including unpredicted redirects/popups", async () => {
  let inputs = 0;
  browse.sessions.set("mock", { backend: "cloud", page: { click: () => inputs++, press: () => inputs++ } });
  try {
    await assert.rejects(browse.click("mock", 1), /request-level/);
    for (const key of ["Enter", "Tab", "Escape"]) await assert.rejects(browse.press("mock", key), /request-level/);
    assert.equal(inputs, 0);
  } finally { browse.sessions.delete("mock"); }
});

test("protected codes and login reject before any vault access or code lookup, for both backends", async () => {
  const initialReads = vaultReads;
  for (const backend of ["cloud", "local"]) for (const host of ["accounts.google.com", "facebook.com", "appleid.apple.com"]) {
    browse.sessions.set("mock", { backend, page: { url: async () => `https://${host}/login` } });
    try {
      for (const source of ["totp", "sms", "email"]) await assert.rejects(vault.codesFill({ session: "mock", id: "synthetic", source }), (error) => error.code === (backend === "cloud" ? "CLOUD_UNAVAILABLE" : "PROTECTED_SITE"));
      await assert.rejects(vault.loginWith({ session: "mock", id: "synthetic" }), (error) => error.code === (backend === "cloud" ? "CLOUD_UNAVAILABLE" : "PROTECTED_SITE"));
    } finally { browse.sessions.delete("mock"); }
  }
  assert.equal(vaultReads, initialReads);
});

test("cloud submission rejects before credential retrieval even on an allowed host", async () => {
  browse.sessions.set("mock", { backend: "cloud", page: { url: async () => "https://example.com/login" } });
  try {
    await assert.rejects(vault.loginWith({ session: "mock", id: "synthetic" }), /request-level/);
    await assert.rejects(vault.codesFill({ session: "mock", id: "synthetic", source: "totp" }), /request-level/);
  } finally { browse.sessions.delete("mock"); }
});

const valid = () => ({ backendAvailable: true, fetch: { ok: true }, domainLockLive: { refused: true, category: "DOMAIN_MISMATCH" }, login: { status: "submitted" }, afterLogin: { authenticatedDashboard: true, stillOnLoginForm: false }, screenshots: { before: true, after: true }, release: { primary: true, other: true }, ledger: { keysOnly: true, hasLogin: true, rows: 3 }, leakScan: { forbiddenForms: 8, hits: [] } });
test("acceptance fails closed for each omitted assertion and failed login", () => {
  assert.deepEqual(acceptanceFailures(valid()), []);
  for (const key of Object.keys(valid())) { const p = valid(); delete p[key]; assert.ok(acceptanceFailures(p).length, key); }
  for (const key of ["domainLockLive", "screenshots", "release", "ledger", "afterLogin"]) for (const field of Object.keys(valid()[key])) {
    const p = valid(); p[key][field] = undefined; assert.ok(acceptanceFailures(p).length, `${key}.${field}`);
  }
  for (const status of ["needs_code", "no_login_form", "filled_not_submitted"]) { const p = valid(); p.login.status = status; assert.ok(acceptanceFailures(p).includes("login")); }
  const p = valid(); p.leakScan.hits.push("synthetic"); assert.ok(acceptanceFailures(p).includes("outputScan"));
});
test("live harness refuses without opt-in, before starting any provider or credential work", () => {
  const r = spawnSync(process.execPath, [path.join(__dirname, "../scripts/e2e-tools.cjs")], { env: { PATH: process.env.PATH }, encoding: "utf8" });
  assert.equal(r.status, 1); assert.match(r.stderr, /separate authorization/);
});

test("allowed local fill works with synthetic credentials; protected, off-domain and downgraded focus navigation prevents insertion", async (t) => {
  const ledger = require("../src/tools/ledger.cjs");
  t.mock.method(ledger, "loginsToday", () => 0);
  t.mock.method(ledger, "record", () => {});
  t.mock.method(browse, "tagged", async () => ({ rows: [{ tag: "input", type: "password", ref: 1, action: "https://example.com/login", name: "password" }] }));
  let url = "https://example.com/login";
  let redirect = false;
  const inserted = [];
  browse.sessions.set("mock", { backend: "local", secrets: new Set(), usernames: new Set(), page: {
    url: async () => url, focus: async () => { if (redirect) url = redirect; }, insert: async (text) => inserted.push(text),
  } });
  try {
    assert.equal((await vault.loginWith({ session: "mock", id: "synthetic", submit: false })).status, "filled_not_submitted");
    assert.deepEqual(inserted, ["synthetic-password"]);
    for (const [destination, code] of [["https://accounts.google.com/login", "PROTECTED_SITE"], ["https://unrelated.test/login", "DOMAIN_MISMATCH"], ["http://example.com/login", "DOMAIN_LOCK_DENIED"]]) {
      url = "https://example.com/login";
      redirect = destination;
      await assert.rejects(vault.loginWith({ session: "mock", id: "synthetic", submit: false }), (error) => error.code === code);
      assert.equal(inserted.length, 1);
    }
  } finally { browse.sessions.delete("mock"); }
});

test("all cloud actions fail before focus, input handlers, DOM evaluation or provider creation; cleanup remains supported", async (t) => {
  const initialReads = vaultReads;
  let operations = 0;
  let released = false;
  const page = Object.fromEntries(["url", "focus", "insert", "eval", "goto", "screenshot", "click", "press"].map((name) => [name, async () => { operations++; throw new Error(`must not call ${name}`); }]));
  t.mock.method(globalThis, "fetch", () => { throw new Error("must not reach provider"); });
  browse.sessions.set("mock", { backend: "cloud", page, label: "synthetic", started: Date.now(), release: async () => { released = true; } });
  try {
    const actions = [() => browse.open(), () => browse.open({ backend: "cloud", url: "https://example.com" }), () => browse.goto("mock", "https://example.com"), () => browse.fill("mock", 1, "synthetic"), () => browse.snapshot("mock"), () => browse.tagged("mock"), () => browse.screenshot("mock"), () => browse.click("mock", 1), () => browse.press("mock", "Enter"), () => vault.loginWith({ session: "mock", id: "synthetic", submit: false }), () => vault.codesFill({ session: "mock", id: "synthetic", source: "sms" })];
    for (const action of actions) await assert.rejects(action(), (error) => error.code === "CLOUD_UNAVAILABLE");
    assert.equal(operations, 0);
    assert.equal(vaultReads, initialReads);
    assert.equal(browse.list().length, 1);
    assert.deepEqual(await browse.stop("mock"), { stopped: "mock" });
    assert.equal(released, true);
  } finally { browse.sessions.delete("mock"); }
});

test("input-triggered cloud navigation never executes; local plain input remains supported", async () => {
  let url = "https://example.com";
  let focused = 0;
  const page = { focus: async () => focused++, insert: async () => { url = "https://accounts.google.com"; } };
  browse.sessions.set("mock", { backend: "cloud", page });
  try {
    await assert.rejects(browse.fill("mock", 1, "synthetic"), (error) => error.code === "CLOUD_UNAVAILABLE");
    assert.equal(url, "https://example.com"); assert.equal(focused, 0);
    browse.sessions.set("mock", { backend: "local", page: { focus: async () => focused++, insert: async (text) => assert.equal(text, "synthetic") } });
    assert.deepEqual(await browse.fill("mock", 1, "synthetic"), { ok: true });
    assert.equal(focused, 1);
  } finally { browse.sessions.delete("mock"); }
});

test("a real saved-site mismatch is categorized distinctly from unavailable functionality", async (t) => {
  t.mock.method(require("../src/tools/ledger.cjs"), "loginsToday", () => 0);
  const page = { url: async () => "https://unrelated.test/login", focus: async () => assert.fail("no focus"), insert: async () => assert.fail("no insertion") };
  browse.sessions.set("mock", { backend: "local", secrets: new Set(), usernames: new Set(), page });
  try {
    await assert.rejects(vault.loginWith({ session: "mock", id: "synthetic", submit: false }), (error) => error.code === "DOMAIN_MISMATCH");
    await assert.rejects(vault.codesFill({ session: "mock", id: "synthetic", source: "totp" }), (error) => error.code === "DOMAIN_MISMATCH");
  } finally { browse.sessions.delete("mock"); }
});

test("domain-lock and overall acceptance reject unavailable, generic and unrelated policy denials", () => {
  for (const category of [undefined, "CLOUD_UNAVAILABLE", "TOOL_ERROR", "PROTECTED_SITE", "DOMAIN_LOCK_DENIED"]) {
    const proof = valid();
    proof.domainLockLive = { refused: true, category, message: "domain lock: does not match the item's saved sites" };
    assert.deepEqual(acceptanceFailures(proof), ["domainLock"]);
  }
  const proof = valid(); proof.backendAvailable = false;
  assert.deepEqual(acceptanceFailures(proof), ["backendAvailable"]);
  proof.domainLockLive.category = "CLOUD_UNAVAILABLE";
  proof.login.status = "unavailable";
  assert.deepEqual(acceptanceFailures(proof), ["backendAvailable", "domainLock", "login"]);
});

test("fully opted-in live harness still exits unavailable before any filesystem, child or provider action", () => {
  const vm = require("node:vm");
  const fs = require("node:fs");
  const source = fs.readFileSync(path.join(__dirname, "../scripts/e2e-tools.cjs"), "utf8");
  let output = "";
  const forbidden = new Proxy({}, { get() { throw new Error("live action reached"); } });
  const context = {
    require(name) {
      if (name === "../src/tools/browse.cjs") return browse;
      if (name === "./tools-acceptance.cjs") return { acceptanceFailures };
      if (name === "node:child_process") return { spawn: () => assert.fail("spawn"), execFileSync: () => assert.fail("credential lookup") };
      return forbidden;
    },
    process: { env: { E2E_LIVE_AUTHORIZED: "1", E2E_AUTH_URL: "https://example.test/dashboard", E2E_AUTH_MARKER: "Synthetic marker" }, exit: (code) => { throw new Error(`EXIT:${code}`); } },
    console: { error: (text) => { output += text; } },
  };
  assert.throws(() => vm.runInNewContext(source, context), /EXIT:1/);
  assert.match(output, /CLOUD_UNAVAILABLE/);
  assert.match(output, /not run/);
});

test("MCP preserves trusted policy categories but cannot promote arbitrary error text/code into evidence", async () => {
  const vm = require("node:vm");
  const fs = require("node:fs");
  const { PolicyError, errorCategory } = require("../src/tools/errors.cjs");
  const { redact } = require("../src/tools/policy.cjs");
  const source = fs.readFileSync(path.join(__dirname, "../src/tools/mcp-server.cjs"), "utf8");
  let thrown;
  const output = [];
  const stream = { on() { return stream; } };
  const context = { require(name) {
    if (name === "node:readline") return { createInterface: () => stream };
    if (name === "./tools.cjs") return { run: async () => { throw thrown; }, secrets: () => [], closeAll: async () => {} };
    if (name === "./errors.cjs") return { errorCategory };
    if (name === "./policy.cjs") return { redact };
    assert.fail(name);
  }, process: { stdout: { write: (line) => output.push(JSON.parse(line)) }, on() {} } };
  vm.createContext(context); vm.runInContext(source, context);
  for (const [error, expected] of [[new PolicyError("DOMAIN_MISMATCH", "saved site mismatch"), "DOMAIN_MISMATCH"], [new PolicyError("CLOUD_UNAVAILABLE", "unavailable"), "CLOUD_UNAVAILABLE"], [Object.assign(new Error("DOMAIN_MISMATCH"), { code: "DOMAIN_MISMATCH" }), "TOOL_ERROR"]]) {
    thrown = error;
    await context.handle({ id: output.length + 1, method: "tools/call", params: { name: "synthetic" } });
    assert.equal(output.at(-1).result.errorCategory, expected);
    assert.equal(output.at(-1).result.isError, true);
  }
});

test("code fill rechecks the saved domain after focus, without submitting or inserting on mismatch", async (t) => {
  const codes = require("../src/tools/codes.cjs");
  const ledger = require("../src/tools/ledger.cjs");
  t.mock.method(codes, "waitForCode", async () => "123456");
  t.mock.method(ledger, "record", () => {});
  t.mock.method(browse, "tagged", async () => ({ rows: [{ tag: "input", type: "text", ac: "one-time-code", ref: 1, action: "https://example.com/verify", name: "otp" }] }));
  let url = "https://example.com/verify";
  browse.sessions.set("mock", { backend: "local", secrets: new Set(), usernames: new Set(), page: {
    url: async () => url, focus: async () => { url = "https://unrelated.test/verify"; },
    insert: async () => assert.fail("code must not be inserted"), press: async () => assert.fail("must not submit"),
  } });
  try {
    await assert.rejects(vault.codesFill({ session: "mock", id: "synthetic", source: "sms" }), (error) => error.code === "DOMAIN_MISMATCH");
  } finally { browse.sessions.delete("mock"); }
});

test("local navigation, click, keypress and snapshot remain supported", async () => {
  let url = "https://example.test/start";
  browse.sessions.set("mock", { backend: "local", secrets: new Set(), page: {
    url: async () => url, goto: async (target) => { url = target; },
    click: async () => { url = "https://example.test/clicked"; },
    press: async () => { url = "https://example.test/pressed"; },
    eval: async () => ({ title: "Synthetic local page", text: "Synthetic", rows: [] }),
  } });
  try {
    assert.deepEqual(await browse.goto("mock", "https://example.test/next"), { url: "https://example.test/next" });
    assert.deepEqual(await browse.click("mock", 1), { url: "https://example.test/clicked" });
    assert.deepEqual(await browse.press("mock", "Enter"), { url: "https://example.test/pressed" });
    assert.equal((await browse.snapshot("mock")).title, "Synthetic local page");
  } finally { browse.sessions.delete("mock"); }
});
