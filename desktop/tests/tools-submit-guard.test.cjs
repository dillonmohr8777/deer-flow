"use strict";

const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { createRequire } = require("node:module");
const browse = require("../src/tools/browse.cjs");

// Deterministic DOM/CDP doubles: no browser, provider, vault, codes or network.
function fixture(t, { action = "/login", override, button = true, sameForm = true, onInsert = () => {} } = {}) {
  let url = "https://example.test/login";
  let submitted = 0;
  let enters = 0;
  let active = true;
  const inserted = [];
  const form = { get action() { return new URL(action, url).href; }, getAttribute: (key) => key === "action" ? action : null, method: "post" };
  const otherForm = { action: "https://example.test/other", getAttribute: () => "https://example.test/other", method: "post" };
  const element = (tag, attrs, owner) => ({
    tagName: tag.toUpperCase(), form: owner, disabled: false, isConnected: true, innerText: tag === "button" ? "Sign in" : "",
    get type() { return attrs.type || (tag === "button" ? "submit" : "text"); },
    get formAction() { return new URL(attrs.formaction ?? "", url).href; },
    getAttribute: (key) => attrs[key] ?? null,
    hasAttribute: (key) => Object.hasOwn(attrs, key),
    setAttribute: (key, value) => { attrs[key] = String(value); },
    removeAttribute: (key) => { delete attrs[key]; },
    matches(selector) { assert.equal(selector, ":disabled"); return this.disabled; },
    getBoundingClientRect: () => ({ width: 100, height: 30 }),
  });
  const field = element("input", { type: "password", name: "password" }, form);
  const submitter = element("button", override === undefined ? {} : { formaction: override }, sameForm ? form : otherForm);
  const elements = button ? [field, submitter] : [field];
  const document = {
    get baseURI() { return url; }, forms: [form, otherForm], title: "Synthetic login", body: { innerText: "Synthetic login" },
    querySelectorAll(selector) { return active ? elements.filter((el) => selector !== "[data-mb-ref]" || el.hasAttribute("data-mb-ref")) : []; },
    querySelector(selector) {
      const ref = selector.match(/data-mb-ref="(\d+)"/u)?.[1];
      return active ? elements.find((el) => el.getAttribute("data-mb-ref") === ref) ?? null : null;
    },
  };
  const context = { document, getComputedStyle: () => ({ visibility: "visible", display: "block" }), URL, location: { get href() { return url; } } };
  const session = { backend: "local", secrets: new Set(), usernames: new Set(), page: {
    url: async () => url,
    eval: async (source) => vm.runInNewContext(source, context),
    focus: async () => {},
    insert: async (value) => { inserted.push(value); onInsert({ form, submitter, field, setAction: (value) => { action = value; }, setUrl: (value) => { url = value; } }); },
    click: async () => { submitted++; active = false; },
    press: async () => { enters++; active = false; },
  } };
  browse.sessions.set("submit-synthetic", session);
  t.after(() => browse.sessions.delete("submit-synthetic"));
  const filename = path.join(__dirname, "../src/tools/vault.cjs");
  const localRequire = createRequire(filename);
  const module = { exports: {} };
  const sandbox = { module, exports: module.exports, require(name) {
    if (name === "node:child_process") return { execFile: (_file, _args, _options, callback) => callback(null, JSON.stringify({ login: {
      username: "synthetic-user", password: "synthetic-password", uris: [{ uri: "https://example.test" }],
    } })) };
    if (name === "./ledger.cjs") return { loginsToday: () => 0, record: () => {} };
    if (name === "./cdp.cjs") return { sleep: async () => {} };
    if (name === "./codes.cjs") return { waitForCode: async () => "123456" };
    return localRequire(name);
  } };
  vm.runInNewContext(fs.readFileSync(filename, "utf8"), sandbox, { filename });
  return { session, field, submitter, form, inserted, document, vault: module.exports, submissions: () => submitted, enters: () => enters };
}

test("tagged resolves the effective submitter destination and default button type", async (t) => {
  fixture(t, { override: "https://unrelated.test/collect" });
  const { rows } = await browse.tagged("submit-synthetic");
  assert.equal(rows[0].action, "https://example.test/login");
  assert.equal(rows[1].action, "https://unrelated.test/collect");
  assert.equal(rows[1].type, "submit");
  assert.equal(rows[0].form, rows[1].form);
});

test("vault rejects an off-site formaction override before clicking", async (t) => {
  const f = fixture(t, { override: "https://unrelated.test/collect" });
  await assert.rejects(f.vault.loginWith({ session: "submit-synthetic", id: "synthetic" }), (error) => error.code === "DOMAIN_MISMATCH");
  assert.equal(f.submissions(), 0);
  assert.equal(f.enters(), 0);
});

for (const [name, mutation, code] of [
  ["form action", ({ setAction }) => setAction("https://unrelated.test/collect"), "DOMAIN_MISMATCH"],
  ["submitter override", ({ submitter }) => submitter.setAttribute("formaction", "https://unrelated.test/collect"), "DOMAIN_MISMATCH"],
  ["HTTPS downgrade", ({ submitter }) => submitter.setAttribute("formaction", "http://example.test/login"), "DOMAIN_LOCK_DENIED"],
  ["protected destination", ({ submitter }) => submitter.setAttribute("formaction", "https://accounts.google.com/login"), "PROTECTED_SITE"],
  ["page navigation", ({ setUrl }) => setUrl("https://unrelated.test/login"), "DOMAIN_MISMATCH"],
  ["disabled submitter", ({ submitter }) => { submitter.disabled = true; }, "DOMAIN_LOCK_DENIED"],
  ["detached form", ({ field }) => { field.form = null; }, "DOMAIN_LOCK_DENIED"],
]) test(`vault rechecks live ${name} after synthetic insertion`, async (t) => {
  const f = fixture(t, { onInsert: mutation });
  await assert.rejects(f.vault.loginWith({ session: "submit-synthetic", id: "synthetic" }), (error) => error.code === code);
  assert.equal(f.submissions(), 0);
  assert.equal(f.enters(), 0);
});

for (const options of [{ button: false }, { sameForm: false }]) test(`vault refuses unknown implicit submission ${JSON.stringify(options)}`, async (t) => {
  const f = fixture(t, options);
  await assert.rejects(f.vault.loginWith({ session: "submit-synthetic", id: "synthetic" }), (error) => error.code === "DOMAIN_LOCK_DENIED");
  assert.equal(f.submissions(), 0);
  assert.equal(f.enters(), 0);
});

test("vault permits an explicit same-form submitter with a saved-site override", async (t) => {
  const f = fixture(t, { override: "https://auth.example.test/verify" });
  assert.equal((await f.vault.loginWith({ session: "submit-synthetic", id: "synthetic" })).status, "submitted");
  assert.equal(f.submissions(), 1);
  assert.equal(f.enters(), 0);
  assert.deepEqual(f.inserted, ["synthetic-password"]);
});

test("standalone code fill applies the same live submitter lock", async (t) => {
  const f = fixture(t, { override: "https://unrelated.test/collect" });
  f.field.setAttribute("type", "text");
  f.field.setAttribute("autocomplete", "one-time-code");
  await assert.rejects(f.vault.codesFill({ session: "submit-synthetic", id: "synthetic", source: "sms" }), (error) => error.code === "DOMAIN_MISMATCH");
  assert.equal(f.submissions(), 0);
  assert.equal(f.enters(), 0);
});
