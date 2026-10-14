"use strict";

const { execFile } = require("node:child_process");
const os = require("node:os");
const path = require("node:path");
const browse = require("./browse.cjs");
const codes = require("./codes.cjs");
const ledger = require("./ledger.cjs");
const { domainLock, cloudBlocked, redact } = require("./policy.cjs");
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
  const buttons = rows.filter((r) => r.type === "submit" || (r.tag === "button" && /sign in|log in|login|continue|next|submit|verify|confirm/iu.test(r.label)));
  const submit = buttons.find((r) => anchor && r.action && r.action === anchor.action) ?? buttons[0];
  return { pass, otp, user, submit };
}

/**
 * Type one secret into one field after the domain lock passes against the browser-reported URL and the form's own action.
 * @param {browse.Session} session @param {readonly string[]} uris @param {{ref:number, action:string}} field @param {string} secret
 */
async function typeLocked(session, uris, field, secret) {
  const here = domainLock(await session.page.url(), uris);
  if (!here.ok) throw new Error(`domain lock: ${here.reason}`);
  if (field.action) {
    const target = domainLock(field.action, uris);
    if (!target.ok) throw new Error(`domain lock: this form posts to a different site (${target.reason})`);
  }
  await session.page.focus(field.ref);
  await session.page.insert(secret);
}

/** @param {browse.Session} session @param {{submit?:{ref:number}}} fields */
async function submit(session, fields) {
  if (fields.submit) await session.page.click(fields.submit.ref); else await session.page.press("Enter");
  await sleep(2800);
}

/**
 * Pull the item here, type username, password and TOTP into the live session, never return them.
 * @param {{session:string, id:string, otp?:"totp"|"sms"|"email", sender?:string, submit?:boolean}} options
 */
async function loginWith({ session: sid, id, otp, sender, submit: doSubmit = true }) {
  const session = browse.get(sid);
  if (ledger.loginsToday(id) >= MAX_LOGINS_PER_DAY) throw new Error(`login limit reached for this item today (${MAX_LOGINS_PER_DAY}); lockout protection`);
  const raw = await bw(["get", "item", id]);
  const login = raw.login ?? {};
  if (!login.username || !login.password) throw new Error("that item has no username and password");
  const uris = /** @type {string[]} */ ((login.uris ?? []).map((/** @type {any} */ u) => u.uri).filter(Boolean));
  session.secrets.add(login.password); session.secrets.add(login.username); session.usernames.add(login.username);
  const first = domainLock(await session.page.url(), uris);
  try {
    if (!first.ok) throw new Error(`domain lock: ${first.reason}`);
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
      await submit(session, fields);
    }
    if (!acted) return { status: "no_login_form", domain: first.domain, url: (await session.page.url()).split(/[?#]/u)[0], note: "no username, password or code field is showing; the session may already be signed in" };
    return redact({ status: "submitted", domain: first.domain, url: (await session.page.url()).split(/[?#]/u)[0], steps, note: "take a screenshot to confirm the login landed" }, session.secrets);
  } catch (error) {
    // eslint-disable-next-line preserve-caught-error -- the original error is deliberately not chained: it could carry a secret
    throw new Error(redact(error instanceof Error ? error.message : "login failed", session.secrets));
  }
}

/** Fetch a one-time code (TOTP seed, iMessage or Gmail) and type it into the page's code field. The code is never returned. */
/** @param {{session:string, id:string, source:"totp"|"sms"|"email", sender?:string, waitSeconds?:number}} options */
async function codesFill({ session: sid, id, source, sender, waitSeconds = 90 }) {
  const session = browse.get(sid);
  const raw = await bw(["get", "item", id]);
  const login = raw.login ?? {};
  const uris = /** @type {string[]} */ ((login.uris ?? []).map((/** @type {any} */ u) => u.uri).filter(Boolean));
  const lock = domainLock(await session.page.url(), uris);
  if (!lock.ok) throw new Error(`domain lock: ${lock.reason}`);
  const { rows } = await browse.tagged(sid);
  const fields = findFields(rows);
  if (!fields.otp) throw new Error("no code field on this page");
  const code = source === "totp" ? (login.totp ? codes.totp(login.totp) : null) : await codes.waitForCode(source, { since: Date.now() / 1000 - 30, sender, waitMs: waitSeconds * 1000 });
  if (!code) return { status: "no_code", source };
  session.secrets.add(code);
  ledger.record({ action: "codes_fill", item: id, domain: lock.domain });
  await typeLocked(session, uris, fields.otp, code);
  await submit(session, fields);
  return redact({ status: "submitted", source, domain: lock.domain, url: (await session.page.url()).split(/[?#]/u)[0] }, session.secrets);
}

module.exports = { search, item, loginWith, codesFill, findFields };
