"use strict";

const { execFile } = require("node:child_process");
const os = require("node:os");
const path = require("node:path");
const { hostOf } = require("./policy.cjs");
const ledger = require("./ledger.cjs");

const WITH_EXPAND = path.join(os.homedir(), ".local", "bin", "with-expand");
const CREDITS_PER_PAGE = 1; // observed Oct 14: 232 credits for 232 successful fetches; the dashboard balance is the authority
let credits = 0;
/** @type {string|undefined} */
let keyCache;

async function apiKey() {
  keyCache ??= process.env.EXPAND_API_KEY || await new Promise((resolve, reject) => execFile(WITH_EXPAND, ["printenv", "EXPAND_API_KEY"], { timeout: 15000 }, (error, out) => error ? reject(new Error("Expand key unavailable (Keychain expand.api-key)")) : resolve(out.trim())));
  return /** @type {string} */ (keyCache);
}

/** Public pages only: Expand fetches from its own servers, so private and local addresses are refused here. @param {string} url */
function publicURL(url) {
  const host = hostOf(url);
  if (!host || host === "localhost" || /^(?:127\.|10\.|192\.168\.|169\.254\.|0\.)/u.test(host) || /^172\.(?:1[6-9]|2\d|3[01])\./u.test(host) || host.endsWith(".local") || host.endsWith(".internal") || host.includes(":") || !host.includes(".")) {
    throw new Error("Fetch is for public http(s) pages only; use Browse for anything behind a login");
  }
  return url;
}

/** Markdown plus hidden JSON (State JSON) for a public page. @param {{url:string, maxChars?:number}} options */
async function fetchPage({ url, maxChars = 20000 }) {
  publicURL(url);
  const response = await fetch("https://api.expand.ai/v1/fetch/json?include=statejson", {
    method: "POST", headers: { "x-expand-api-key": await apiKey(), "content-type": "application/json" },
    body: JSON.stringify({ url }), signal: AbortSignal.timeout(90000),
  });
  if (!response.ok) throw new Error(`Expand fetch failed: HTTP ${response.status}${response.status >= 500 || response.status === 429 ? " (not billed)" : ""}`);
  const data = await response.json();
  credits += CREDITS_PER_PAGE;
  ledger.record({ action: "fetch", domain: hostOf(url) });
  const markdown = String(data.markdown ?? "");
  return {
    url: data.meta?.url ?? url, title: data.meta?.title ?? null, pageType: data.meta?.pageType ?? null,
    markdown: markdown.slice(0, maxChars), markdownChars: markdown.length, truncated: markdown.length > maxChars,
    hiddenJson: data.json ?? [], stateJson: data.statejson ?? data.stateJson ?? null, snapshot: data.meta?.playground ?? null,
    credits: { thisCall: CREDITS_PER_PAGE, thisRun: credits, fetchesToday: ledger.read().filter((row) => row.action === "fetch" && row.ts.startsWith(new Date().toISOString().slice(0, 10))).length, note: "1 credit per page ($1 per 1,000); dashboard balance is authoritative" },
  };
}

module.exports = { fetchPage, publicURL };
