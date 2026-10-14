"use strict";

// Access concierge bridge: a teammate (identified by Slack user id) asks for a client login. The Python concierge in
// ~/code/_setup/browser-agents checks per-person policy, logs in with an injected credential, pulls 2FA codes from the
// right inbox, and returns a live-view link. This process only relays arguments and the JSON reply: no secret passes here.
// `asker` MUST come from the verified Slack event (user id), never from model-written text.
const { execFile } = require("node:child_process");
const os = require("node:os");
const path = require("node:path");

const AGENTS = path.join(os.homedir(), "code", "_setup", "browser-agents");
const LAUNCHER = path.join(os.homedir(), ".local", "bin", "with-browserbase");

/** Test seam: MOMO_CONCIERGE_CMD is a JSON array that replaces the launcher + python + script prefix. @returns {string[]} */
function prefix() {
  if (process.env.MOMO_CONCIERGE_CMD) return JSON.parse(process.env.MOMO_CONCIERGE_CMD);
  return [LAUNCHER, path.join(AGENTS, ".venv", "bin", "python"), path.join(AGENTS, "concierge.py")];
}

/** @param {string[]} args @returns {Promise<any>} */
function call(args) {
  const [file, ...rest] = prefix();
  return new Promise((resolve, reject) => execFile(file, [...rest, ...args], { cwd: AGENTS, timeout: 240000, maxBuffer: 1 << 20 }, (error, stdout) => {
    let parsed;
    try { parsed = JSON.parse(stdout.trim().split("\n").pop() || ""); } catch { /* fall through */ }
    if (parsed) return resolve(parsed);
    return reject(new Error(error ? "concierge failed to run" : "concierge returned unreadable output")); // never echo raw stdout/stderr
  }));
}

/** @param {{asker:string, text?:string, client?:string, site?:string, action?:string, handoff?:string}} a */
function request(a) {
  const args = ["request", "--who", a.asker];
  for (const key of /** @type {const} */ (["text", "client", "site", "action"])) { const value = a[key]; if (value) args.push(`--${key}`, value); }
  if (String(a.handoff) === "false") args.push("--no-handoff");
  return call(args);
}

/** @param {{asker:string}} a */
function status(a) { return call(["status", "--who", a.asker]); }

module.exports = { request, status };
