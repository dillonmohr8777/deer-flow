"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { test } = require("node:test");
const { domainLock, cloudBlocked, redact } = require("../src/tools/policy.cjs");
const { totp, extract } = require("../src/tools/codes.cjs");

const saved = ["https://expand.ai/login", "app.netlify.com"];

test("domain lock: exact host, www and subdomains of a saved site match", () => {
  assert.deepEqual(domainLock("https://expand.ai/login", saved), { ok: true, domain: "expand.ai" });
  assert.deepEqual(domainLock("https://www.expand.ai/dashboard?x=1", saved), { ok: true, domain: "expand.ai" });
  assert.deepEqual(domainLock("https://auth.expand.ai/", saved), { ok: true, domain: "expand.ai" });
  assert.deepEqual(domainLock("https://EXPAND.AI./", saved), { ok: true, domain: "expand.ai" });
  assert.equal(domainLock("https://app.netlify.com/teams", saved).ok, true);
});

test("domain lock: lookalikes, parents of a saved subdomain, downgrades and credentials in the URL are refused", () => {
  for (const url of [
    "https://evil.com/", "https://expand.ai.evil.com/", "https://notexpand.ai/", "https://expand.ai@evil.com/", "https://evil.com/expand.ai",
    "https://xn--expnd-6ua.ai/", "http://expand.ai/login", "https://user:pw@expand.ai/", "https://netlify.com/", "javascript:alert(1)", "not a url", "about:blank",
  ]) assert.equal(domainLock(url, saved).ok, false, url);
});

test("domain lock: an item with no saved website, or only app URIs, never matches", () => {
  assert.equal(domainLock("https://expand.ai/", []).ok, false);
  assert.equal(domainLock("https://expand.ai/", ["androidapp://com.example", ""]).ok, false);
});

test("Google, Facebook and Apple hosts are blocked on cloud browsers", () => {
  for (const url of ["https://accounts.google.com/signin", "https://www.facebook.com/", "https://appleid.apple.com/", "https://mail.google.com", "https://icloud.com"]) assert.equal(cloudBlocked(url), true, url);
  for (const url of ["https://expand.ai/", "https://notgoogle.com/", "https://google.com.evil.com/", "https://app.netlify.com/"]) assert.equal(cloudBlocked(url), false, url);
});

test("redaction removes secrets and their URL, JSON and base64 forms from strings and nested values", () => {
  const secrets = ["p@ss w0rd!\"x", "dillon@example.com"];
  const out = redact({
    a: "logged in as dillon@example.com using p@ss w0rd!\"x",
    b: [`pw=${encodeURIComponent(secrets[0])}`, JSON.stringify({ password: secrets[0] }), Buffer.from(secrets[0]).toString("base64")],
    c: { nested: "dillon@example.com" }, n: 7,
  }, secrets);
  const text = JSON.stringify(out);
  for (const secret of secrets) for (const form of [secret, encodeURIComponent(secret), JSON.stringify(secret).slice(1, -1), Buffer.from(secret).toString("base64")]) assert.equal(text.includes(form), false, form);
  assert.equal(out.n, 7);
  assert.equal(redact("ordinary page text", secrets), "ordinary page text");
  assert.equal(redact("a b c", ["a", ""]), "a b c");
});

test("TOTP matches the RFC 6238 vectors and codes are extracted from messages", () => {
  const seed = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ";
  assert.equal(totp(seed, 59), "287082");
  assert.equal(totp(seed, 1111111109), "081804");
  assert.equal(totp(`otpauth://totp/x?secret=${seed}&digits=8`, 59), "94287082");
  assert.equal(extract("Your Expand code is 482913. Don't share."), "482913");
  assert.equal(extract("order 1234567 shipped"), null);
});

test("the ledger records ids, domains and times only, appends, and caps logins per item per day", () => {
  process.env.MOMOBOT_TOOLS_HOME = fs.mkdtempSync(path.join(os.tmpdir(), "momobot-tools-"));
  const ledger = require("../src/tools/ledger.cjs");
  ledger.record({ action: "login_with", item: "abc-123", domain: "expand.ai" });
  ledger.record({ action: "login_with", item: "abc-123", domain: "expand.ai" });
  ledger.record({ action: "fetch", domain: "example.com" });
  const rows = ledger.read();
  assert.equal(rows.length, 3);
  for (const row of rows) assert.deepEqual(Object.keys(row).sort(), ["action", "domain", "item", "ts"]);
  assert.equal(ledger.loginsToday("abc-123"), 2);
  assert.equal(ledger.loginsToday("other"), 0);
  assert.equal(fs.statSync(ledger.ledgerPath()).mode & 0o777, 0o600);
});
