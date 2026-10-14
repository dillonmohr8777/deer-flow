"use strict";

const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

function home() {
  const dir = process.env.MOMOBOT_TOOLS_HOME || path.join(os.homedir(), "Library", "Application Support", "MomoBot", "tools");
  fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
  return dir;
}

function ledgerPath() { return path.join(home(), "ledger.jsonl"); }

/**
 * Append-only use record. Only an item id (or null), a domain, an action and a timestamp: no values, no URLs, no page text.
 * @param {{action:string, item?:string|null, domain?:string|null}} entry
 */
function record({ action, item = null, domain = null }) {
  const line = JSON.stringify({ ts: new Date().toISOString(), action, item, domain });
  fs.appendFileSync(ledgerPath(), `${line}\n`, { mode: 0o600 });
}

/** @returns {{ts:string, action:string, item:string|null, domain:string|null}[]} */
function read() {
  try {
    return fs.readFileSync(ledgerPath(), "utf8").split("\n").filter(Boolean).map((line) => JSON.parse(line));
  } catch { return []; }
}

/** Login attempts today (UTC day) for one item: lockout protection, max 2 like browser-agents policy login.relogin. */
/** @param {string} item */
function loginsToday(item) {
  const today = new Date().toISOString().slice(0, 10);
  return read().filter((row) => row.action === "login_with" && row.item === item && row.ts.startsWith(today)).length;
}

module.exports = { home, ledgerPath, record, read, loginsToday };
