"use strict";

const { execFile } = require("node:child_process");
const os = require("node:os");
const path = require("node:path");
const browse = require("./browse.cjs");
const codes = require("./codes.cjs");
const ledger = require("./ledger.cjs");
const { domainLock, cloudBlocked, redact } = require("./policy.cjs");
const { PolicyError } = require("./errors.cjs");
const { sleep } = require("./cdp.cjs");

// The wrapper injects the Keychain-held session (bw-session); this process never sees or stores it.
const BW = path.join(os.homedir(), ".local", "bin", "bw");
const MAX_LOGINS_PER_DAY = 2;

/** @param {string[]} args @returns {Promise<any>} */
function bw(args) {
  return new Promise((resolve, reject) => execFile(BW, args, { timeout: 30000, maxBuffer: 16 << 20 }, (error, stdout) => {
    if (error) return reject(new Error("Bitwarden CLI failed (is the vault unlocked? try: bw status)"));
    try { resolve(JSON.parse(stdout)); } catch { reject(new Error("Bitwarden CLI returned unreadable output")); }
  }));
}

/** Metadata only: never usernames, passwords, TOTP seeds, notes or custom field values. @param {any} item */
function meta(item) {
  const login = item.login ?? {};
  return {
    id: item.id, name: item.name, type: { 1: "login", 2: "note", 3: "card", 4: "identity" }[/** @type {1|2|3|4} */ (item.type)] ?? "other",
    uris: (login.uris ?? []).map((/** @type {any} */ u) => u.uri).filter(Boolean), hasUsername: !!login.username, hasPassword: !!login.password, hasTotp: !!login.totp,
    folderId: item.folderId ?? null, customFieldNames: (item.fields ?? []).map((/** @type {any} */ f) => f.name), revised: item.revisionDate,
  };
}

/** @param {{query:string, limit?:number}} options */
async function search({ query, limit = 20 }) {
  const items = await bw(["list", "items", "--search", query]);
  return items.slice(0, Math.min(limit, 50)).map(meta);
}

/** @param {{id:string}} options */
async function item({ id }) {
  const found = meta(await bw(["get", "item", id]));
  ledger.record({ action: "vault_item", item: id, domain: null });
  return found;
}

const NOT_FIELD = new Set(["hidden", "checkbox", "radio", "submit", "button", "file", "image", "reset"]);
/** @param {any} r */
const isOtp = (r) => r.ac === "one-time-code" || (r.type !== "password" && /otp|totp|2fa|mfa|verif|authcode|passcode|code/iu.test(`${r.name} ${r.placeholder} ${r.label}`));

/** @param {any[]} rows */
function findFields(rows) {
  const inputs = rows.filter((r) => r.tag === "input" && !NOT_FIELD.has(r.type));
  const pass = inputs.find((r) => r.type === "password");
  const otp = inputs.find(isOtp);
  const user = inputs.find((r) => r !== otp && r.type !== "password" && ["", "text", "email", "tel"].includes(r.type));
  const anchor = pass ?? otp ?? user;
  const buttons = rows.filter((r) => (r.tag === "button" || r.tag === "input") && r.type === "submit");
  const submit = anchor && anchor.form != null && anchor.form >= 0 ? buttons.find((r) => r.form === anchor.form) : undefined;
  return { pass, otp, user, submit };
}

/**
 * Type one secret into one field after the domain lock passes against the browser-reported URL and the form's own action.
 * @param {browse.Session} session @param {readonly string[]} uris @param {{ref:number, action:string}} field @param {string} secret
 */
async function typeLocked(session, uris, field, secret) {
  browse.assertInteractiveNavigation(session);
  await assertAutofillAllowed(session);
  if (field.action && cloudBlocked(field.action)) throw new PolicyError("PROTECTED_SITE", "Protected-site form action cannot be auto-filled");
  const here = domainLock(await session.page.url(), uris);
  if (!here.ok) throw new PolicyError(here.category, `domain lock: ${here.reason}`);
  if (field.action) {
    const target = domainLock(field.action, uris);
    if (!target.ok) throw new PolicyError(target.category, `domain lock: this form posts to a different site (${target.reason})`);
  }
  await session.page.focus(field.ref);
  await assertAutofillAllowed(session);
  // Focus handlers may change location. Recheck the complete saved-site lock,
  // not just the protected-host denylist, immediately before secret insertion.
  const focused = domainLock(await session.page.url(), uris);
  if (!focused.ok) throw new PolicyError(focused.category, `domain lock after focus: ${focused.reason}`);
  await session.page.insert(secret);
}

/**
 * Recheck the live native submitter after secret insertion; unknown implicit submissions fail closed.
 * This DOM check does not prevent arbitrary page JavaScript from sending data.
 * @param {browse.Session} session @param {readonly string[]} uris
 * @param {{submit?:{ref:number},pass?:{ref:number},otp?:{ref:number},user?:{ref:number}}} fields
 */
async function submit(session, uris, fields) {
  browse.assertInteractiveNavigation(session);
  await assertAutofillAllowed(session);
  const anchor = fields.pass ?? fields.otp ?? fields.user;
  if (!anchor || !fields.submit) throw new PolicyError("DOMAIN_LOCK_DENIED", "Cannot determine an explicit submitter for this credential form; implicit submission is unavailable");
  const here = domainLock(await session.page.url(), uris);
  if (!here.ok) throw new PolicyError(here.category, `domain lock before submission: ${here.reason}`);
  const target = await session.page.eval(`(() => {
    const field = document.querySelector('[data-mb-ref="${Number(anchor.ref)}"]');
    const button = document.querySelector('[data-mb-ref="${Number(fields.submit.ref)}"]');
    if (!field || !button || !field.isConnected || !button.isConnected || !field.form || field.form !== button.form ||
        !['BUTTON', 'INPUT'].includes(button.tagName) || button.type !== 'submit' ||
        button.matches(':disabled') || field.matches(':disabled') || button.form.method === 'dialog') return null;
    try { return { action: new URL(button.hasAttribute('formaction') ? button.formAction : button.form.action, document.baseURI).href }; }
    catch { return null; }
  })()`);
  if (!target?.action) throw new PolicyError("DOMAIN_LOCK_DENIED", "Cannot verify the live credential form submitter");
  if (cloudBlocked(target.action)) throw new PolicyError("PROTECTED_SITE", "Protected-site form destination cannot be submitted");
  const destination = domainLock(target.action, uris);
  if (!destination.ok) throw new PolicyError(destination.category, `domain lock: submitter posts to a different site (${destination.reason})`);
  await assertAutofillAllowed(session);
  const current = domainLock(await session.page.url(), uris);
  if (!current.ok) throw new PolicyError(current.category, `domain lock before click: ${current.reason}`);
  await session.page.click(fields.submit.ref);
  await sleep(2800);
}

/** @param {browse.Session} session */
async function assertAutofillAllowed(session) {
  if (cloudBlocked(await session.page.url())) throw new PolicyError("PROTECTED_SITE", "Google, Facebook and Apple logins are never auto-filled; reuse a trusted local profile");
}

/**
 * Pull the item here, type username, password and TOTP into the live session, never return them.
 * @param {{session:string, id:string, otp?:"totp"|"sms"|"email", sender?:string, submit?:boolean}} options
 */
async function loginWith({ session: sid, id, otp, sender, submit: doSubmit = true }) {
  const session = browse.get(sid);
  browse.assertInteractiveNavigation(session);
  await assertAutofillAllowed(session);
  if (ledger.loginsToday(id) >= MAX_LOGINS_PER_DAY) throw new Error(`login limit reached for this item today (${MAX_LOGINS_PER_DAY}); lockout protection`);
  const raw = await bw(["get", "item", id]);
  const login = raw.login ?? {};
  if (!login.username || !login.password) throw new Error("that item has no username and password");
  const uris = /** @type {string[]} */ ((login.uris ?? []).map((/** @type {any} */ u) => u.uri).filter(Boolean));
  session.secrets.add(login.password); session.secrets.add(login.username); session.usernames.add(login.username);
  const first = domainLock(await session.page.url(), uris);
  try {
    if (!first.ok) throw new PolicyError(first.category, `domain lock: ${first.reason}`);
    if (cloudBlocked(await session.page.url())) throw new Error("Google, Facebook and Apple logins are never automated; sign in once through trust_device.py and reuse the local profile");
    ledger.record({ action: "login_with", item: id, domain: first.domain });
    let steps = 0, acted = 0;
    for (; steps < 4; steps++) {
      const { rows } = await browse.tagged(sid);
      const fields = findFields(rows);
      const since = Date.now() / 1000;
      if (fields.pass) {
        if (fields.user) await typeLocked(session, uris, fields.user, login.username);
        await typeLocked(session, uris, fields.pass, login.password);
      } else if (fields.otp) {
        let code = null;
        if (otp === "sms" || otp === "email") code = await codes.waitForCode(otp, { since: since - 30, sender });
        else if (login.totp) code = codes.totp(login.totp);
        if (!code) return redact({ status: "needs_code", domain: first.domain, note: "a code field is showing; no code source was available (pass otp: sms or email, or add a TOTP seed to the item)" }, session.secrets);
        session.secrets.add(code);
        await typeLocked(session, uris, fields.otp, code);
      } else if (fields.user && steps === 0) {
        await typeLocked(session, uris, fields.user, login.username);
      } else break;
      acted++;
      if (!doSubmit) return { status: "filled_not_submitted", domain: first.domain };
      await submit(session, uris, fields);
    }
    if (!acted) return { status: "no_login_form", domain: first.domain, url: (await session.page.url()).split(/[?#]/u)[0], note: "no username, password or code field is showing; the session may already be signed in" };
    return redact({ status: "submitted", domain: first.domain, url: (await session.page.url()).split(/[?#]/u)[0], steps, note: "take a screenshot to confirm the login landed" }, session.secrets);
  } catch (error) {
    const message = redact(error instanceof Error ? error.message : "login failed", session.secrets);
    if (error instanceof PolicyError) throw new PolicyError(error.code, message);
    // eslint-disable-next-line preserve-caught-error -- never chain an error that may carry a secret
    throw new Error(message);
  }
}

/** Fetch a one-time code (TOTP seed, iMessage or Gmail) and type it into the page's code field. The code is never returned. */
/** @param {{session:string, id:string, source:"totp"|"sms"|"email", sender?:string, waitSeconds?:number}} options */
async function codesFill({ session: sid, id, source, sender, waitSeconds = 90 }) {
  const session = browse.get(sid);
  browse.assertInteractiveNavigation(session);
  await assertAutofillAllowed(session);
  const raw = await bw(["get", "item", id]);
  const login = raw.login ?? {};
  const uris = /** @type {string[]} */ ((login.uris ?? []).map((/** @type {any} */ u) => u.uri).filter(Boolean));
  const lock = domainLock(await session.page.url(), uris);
  if (!lock.ok) throw new PolicyError(lock.category, `domain lock: ${lock.reason}`);
  const { rows } = await browse.tagged(sid);
  const fields = findFields(rows);
  if (!fields.otp) throw new Error("no code field on this page");
  const code = source === "totp" ? (login.totp ? codes.totp(login.totp) : null) : await codes.waitForCode(source, { since: Date.now() / 1000 - 30, sender, waitMs: waitSeconds * 1000 });
  if (!code) return { status: "no_code", source };
  session.secrets.add(code);
  ledger.record({ action: "codes_fill", item: id, domain: lock.domain });
  await typeLocked(session, uris, fields.otp, code);
  await submit(session, uris, fields);
  return redact({ status: "submitted", source, domain: lock.domain, url: (await session.page.url()).split(/[?#]/u)[0] }, session.secrets);
}

module.exports = { search, item, loginWith, codesFill, findFields };
