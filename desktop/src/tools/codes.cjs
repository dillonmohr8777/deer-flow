"use strict";

const { execFile } = require("node:child_process");
const crypto = require("node:crypto");
const os = require("node:os");
const path = require("node:path");

const CHAT_DB = path.join(os.homedir(), "Library", "Messages", "chat.db");
const APPLE_EPOCH = 978307200;
const DEFAULT_RE = /(?<!\d)(\d{6})(?!\d)/u;
const COMPOSIO = path.join(os.homedir(), ".local", "bin", "composio");

/** @param {string|null|undefined} text */
function extract(text, regex = DEFAULT_RE) {
  const match = regex.exec(text || "");
  return match ? match[1] : null;
}

/** RFC 6238 from a base32 seed or otpauth:// URI. @param {string} seed @param {number} [at] */
function totp(seed, at = Date.now() / 1000) {
  let digits = 6, period = 30, algo = "sha1";
  if (seed.startsWith("otpauth://")) {
    const query = new URL(seed).searchParams;
    seed = query.get("secret") ?? "";
    digits = Number(query.get("digits") ?? 6);
    period = Number(query.get("period") ?? 30);
    algo = (query.get("algorithm") ?? "SHA1").toLowerCase();
  }
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const char of seed.replace(/[\s=]/gu, "").toUpperCase()) {
    const index = alphabet.indexOf(char);
    if (index < 0) throw new Error("unreadable TOTP seed");
    bits += index.toString(2).padStart(5, "0");
  }
  const key = Buffer.from(bits.match(/.{8}/gu)?.map((byte) => parseInt(byte, 2)) ?? []);
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(at / period)));
  const mac = crypto.createHmac(algo, key).update(counter).digest();
  const offset = (mac[mac.length - 1] ?? 0) & 0x0f;
  return String((mac.readUInt32BE(offset) & 0x7fffffff) % 10 ** digits).padStart(digits, "0");
}

/** @param {string} file @param {string[]} args @returns {Promise<string>} */
function run(file, args) {
  return new Promise((resolve, reject) => execFile(file, args, { timeout: 60000, maxBuffer: 4 << 20 }, (error, stdout) => error ? reject(error) : resolve(stdout)));
}

/** Newest incoming iMessage/SMS code after `since` (unix s). Read-only; needs Full Disk Access for the host app. @param {number} since @param {string} [sender] */
async function smsCode(since, sender, regex = DEFAULT_RE, db = CHAT_DB) {
  const cutoff = Math.trunc((since - APPLE_EPOCH) * 1e9);
  const sql = `SELECT hex(COALESCE(m.text,'')), hex(COALESCE(m.attributedBody,'')), COALESCE(h.id,'') FROM message m LEFT JOIN handle h ON h.ROWID=m.handle_id WHERE m.is_from_me=0 AND m.date > ${cutoff} ORDER BY m.date DESC LIMIT 20;`;
  const out = await run("/usr/bin/sqlite3", ["-readonly", "-separator", "|", db, sql]);
  for (const line of out.split("\n").filter(Boolean)) {
    const [text = "", body = "", handle = ""] = line.split("|");
    if (sender && !handle.toLowerCase().includes(sender.toLowerCase())) continue;
    const code = extract(Buffer.from(text || body, "hex").toString("utf8"), regex);
    if (code) return code;
  }
  return null;
}

/** Code from the newest matching Gmail message through Composio. @param {number} since @param {string} [sender] */
async function emailCode(since, sender, regex = DEFAULT_RE) {
  const query = [`after:${Math.trunc(since) - 60}`, sender ? `from:${sender}` : ""].filter(Boolean).join(" ");
  const out = await run(COMPOSIO, ["execute", "GMAIL_FETCH_EMAILS", "-d", JSON.stringify({ query, max_results: 3, include_payload: true })]);
  const data = JSON.parse(out);
  const inner = data?.data ?? data;
  /** @param {any} node @returns {string[]} */
  const strings = (node) => typeof node === "string" ? [node] : node && typeof node === "object" ? Object.values(node).flatMap(strings) : [];
  for (const message of inner?.messages ?? [data]) {
    for (const text of strings(message)) {
      const code = extract(text, regex);
      if (code) return code;
    }
  }
  return null;
}

/**
 * Poll SMS/email until a code appears. The code is returned to the caller to type once; never logged.
 * @param {"sms"|"email"} source @param {{since:number, sender?:string, waitMs?:number, regex?:RegExp}} options
 */
async function waitForCode(source, { since, sender, waitMs = 90000, regex = DEFAULT_RE }) {
  const end = Date.now() + waitMs;
  do {
    const code = await (source === "sms" ? smsCode(since, sender, regex) : emailCode(since, sender, regex));
    if (code) return code;
    await new Promise((resolve) => setTimeout(resolve, 5000));
  } while (Date.now() < end);
  return null;
}

module.exports = { extract, totp, smsCode, emailCode, waitForCode };
