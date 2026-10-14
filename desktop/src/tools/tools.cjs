"use strict";

// One registry, two surfaces: the Tools panel (people) and the stdio MCP server (agents). Both call run().
const browse = require("./browse.cjs");
const expand = require("./expand.cjs");
const vault = require("./vault.cjs");

/** @typedef {{type:"string"|"number"|"boolean", description:string, required?:boolean, enum?:string[]}} Field */
/** @typedef {{name:string, group:string, description:string, input:Record<string, Field>, run:(args:any)=>Promise<any>}} Tool */

const session = { type: /** @type {const} */ ("string"), description: "Session id from browse_open", required: true };
/** @type {Tool[]} */
const TOOLS = [
  { name: "browse_open", group: "Browse", description: "Open a browser session. backend cloud = Browserbase with a saved login context (never Google/Facebook/Apple); backend local = this Mac's trusted Chrome profile (use it for Google, Facebook, Apple).",
    input: { backend: { type: "string", description: "cloud (default) or local", enum: ["cloud", "local"] }, url: { type: "string", description: "Page to open first" }, context: { type: "string", description: "Browserbase context name or id (default: derived from the site)" }, profile: { type: "string", description: "Local Chrome profile name (default: derived from the site)" } },
    run: (a) => browse.open(a) },
  { name: "browse_goto", group: "Browse", description: "Navigate an open session to a URL.", input: { session, url: { type: "string", description: "http(s) URL", required: true } }, run: (a) => browse.goto(a.session, a.url) },
  { name: "browse_snapshot", group: "Browse", description: "Page text plus numbered interactive elements. Use the numbers as refs for click and fill. Input values are never shown.", input: { session }, run: (a) => browse.snapshot(a.session) },
  { name: "browse_click", group: "Browse", description: "Click an element by ref from the latest snapshot.", input: { session, ref: { type: "number", description: "Element ref", required: true } }, run: (a) => browse.click(a.session, Number(a.ref)) },
  { name: "browse_fill", group: "Browse", description: "Type plain, non-secret text into an input by ref. Secrets go through vault_login_with, never through here.", input: { session, ref: { type: "number", description: "Input ref", required: true }, text: { type: "string", description: "Text to type", required: true } }, run: (a) => browse.fill(a.session, Number(a.ref), a.text) },
  { name: "browse_press", group: "Browse", description: "Press Enter, Tab or Escape.", input: { session, key: { type: "string", description: "Key", required: true, enum: ["Enter", "Tab", "Escape"] } }, run: (a) => browse.press(a.session, a.key) },
  { name: "browse_screenshot", group: "Browse", description: "Screenshot with every input and any logged-in username blurred. Saved on this Mac; returns the file path.", input: { session }, run: async (a) => { const { base64, ...rest } = await browse.screenshot(a.session); return { ...rest, bytes: Math.round(base64.length * 0.75), _image: base64 }; } },
  { name: "browse_stop", group: "Browse", description: "Close a session and confirm release (cloud contexts save their cookies on a clean stop).", input: { session }, run: (a) => browse.stop(a.session) },
  { name: "fetch_page", group: "Fetch", description: "Expand fetch for PUBLIC pages: markdown plus hidden JSON, and the credit count. Not for anything behind a login.", input: { url: { type: "string", description: "Public http(s) URL", required: true }, maxChars: { type: "number", description: "Markdown length cap (default 20000)" } }, run: (a) => expand.fetchPage({ url: a.url, maxChars: a.maxChars ? Number(a.maxChars) : undefined }) },
  { name: "vault_search", group: "Vault", description: "Search Bitwarden items. Returns metadata only (id, name, saved sites, whether a password or TOTP exists), never secrets.", input: { query: { type: "string", description: "Search text", required: true } }, run: (a) => vault.search({ query: a.query }) },
  { name: "vault_item", group: "Vault", description: "Metadata for one Bitwarden item by id. Never returns secrets.", input: { id: { type: "string", description: "Item id", required: true } }, run: (a) => vault.item({ id: a.id }) },
  { name: "vault_login_with", group: "Vault", description: "Log in to the page in a session using a Bitwarden item. The item is read on this Mac and typed into the page only if the page host matches the item's saved sites. Fills username, password and TOTP, and returns no secrets. Max 2 per item per day.",
    input: { session, id: { type: "string", description: "Bitwarden item id", required: true }, otp: { type: "string", description: "Code source if the site texts or emails a code (default: the item's TOTP)", enum: ["totp", "sms", "email"] }, sender: { type: "string", description: "SMS handle or email sender to match for the code" } },
    run: (a) => vault.loginWith({ session: a.session, id: a.id, otp: a.otp, sender: a.sender }) },
  { name: "codes_fill", group: "Codes", description: "Fetch a one-time code (TOTP seed, iMessage, Gmail) and type it into the page's code field. The code is never returned. Domain-locked to the item.",
    input: { session, id: { type: "string", description: "Bitwarden item id for the site", required: true }, source: { type: "string", description: "Where the code comes from", required: true, enum: ["totp", "sms", "email"] }, sender: { type: "string", description: "SMS handle or email sender to match" } },
    run: (a) => vault.codesFill({ session: a.session, id: a.id, source: a.source, sender: a.sender }) },
];

/** @param {string} name @param {Record<string, unknown>} args */
async function run(name, args) {
  const tool = TOOLS.find((candidate) => candidate.name === name);
  if (!tool) throw new Error(`unknown tool ${name}`);
  for (const [key, field] of Object.entries(tool.input)) if (field.required && (args[key] === undefined || args[key] === "")) throw new Error(`${name} needs ${key}`);
  return tool.run(args);
}

/** @param {Tool} tool */
function jsonSchema(tool) {
  return {
    type: "object",
    properties: Object.fromEntries(Object.entries(tool.input).map(([key, field]) => [key, { type: field.type, description: field.description, ...(field.enum ? { enum: field.enum } : {}) }])),
    required: Object.entries(tool.input).filter(([, field]) => field.required).map(([key]) => key),
  };
}

/** Every secret currently held by an open session, for scrubbing error text. */
function secrets() { return [...browse.sessions.values()].flatMap((s) => [...s.secrets]); }

module.exports = { TOOLS, run, jsonSchema, secrets, closeAll: browse.closeAll, sessions: browse.list };
