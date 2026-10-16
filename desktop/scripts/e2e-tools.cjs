"use strict";

// Live acceptance for MomoBot Desktop Tools, driven through the agent surface (the stdio MCP server).
//   1. Fetch a public page with Expand.   2. Browse + Vault: log into expand.ai from a Browserbase cloud browser.
//   3. Capture screenshots. 4. Scan textual output/ledger; PNG bytes do not prove visual redaction.
// Spends ~2 Expand credits and one short Browserbase session. Needs bw unlocked, with-expand and with-browserbase.
const { spawn, execFileSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const { CLOUD_AUTOMATION_AVAILABLE } = require("../src/tools/browse.cjs");
const { acceptanceFailures } = require("./tools-acceptance.cjs");
// Refuse before spawning the server or reading a credential. This flag is not approval.
if (process.env.E2E_LIVE_AUTHORIZED !== "1" || !process.env.E2E_AUTH_URL || !process.env.E2E_AUTH_MARKER) {
  console.error("Live acceptance requires separate authorization and verified E2E_AUTH_URL/E2E_AUTH_MARKER. Run offline tests by default.");
  process.exit(1);
}
if (!CLOUD_AUTOMATION_AVAILABLE) {
  console.error("CLOUD_UNAVAILABLE: cloud login acceptance was not run. No domain-lock or end-to-end success may be claimed.");
  process.exit(1);
}
const ITEM = process.env.E2E_ITEM || "20907445-142d-4df0-9424-b4e3011afd54"; // Bitwarden: Expand (expand.ai) login
const home = fs.mkdtempSync(path.join(os.tmpdir(), "momobot-tools-e2e-"));
const evidence = path.join(process.env.E2E_EVIDENCE || home, "e2e-evidence.json");

/** @type {string[]} */
const transcript = [];
const child = spawn(process.execPath, [path.join(__dirname, "../src/tools/mcp-server.cjs")], { stdio: ["pipe", "pipe", "pipe"], env: { ...process.env, MOMOBOT_TOOLS_HOME: home } });
/** @type {any[]} */
const replies = [];
let buffer = "";
child.stdout.on("data", (chunk) => { transcript.push(String(chunk)); buffer += chunk; const parts = buffer.split("\n"); buffer = parts.pop() ?? ""; for (const line of parts) if (line) replies.push(JSON.parse(line)); });
child.stderr.on("data", (chunk) => transcript.push(String(chunk)));
let nextId = 0;
/** @param {string} method @param {any} [params] @returns {Promise<any>} */
async function rpc(method, params) {
  const id = ++nextId;
  child.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", id, method, params })}\n`);
  for (let i = 0; i < 1200; i++) { const hit = replies.find((reply) => reply.id === id); if (hit) return hit.result; await new Promise((resolve) => setTimeout(resolve, 100)); }
  throw new Error(`no reply to ${method}`);
}
/** @param {string} name @param {any} args */
async function call(name, args) {
  const result = await rpc("tools/call", { name, arguments: args });
  const text = result.content.find((/** @type {any} */ c) => c.type === "text")?.text ?? "";
  const hasImage = result.content.some((/** @type {any} */ c) => c.type === "image");
  console.log(`${result.isError ? "ERR" : "ok "} ${name} ${result.isError ? text : ""}`);
  return { error: result.isError, category: result.errorCategory, text, hasImage, data: result.isError ? null : JSON.parse(text) };
}

(async () => {
  const proof = /** @type {Record<string, any>} */ ({ backendAvailable: CLOUD_AUTOMATION_AVAILABLE, scope: "source MCP harness", packagedAppAcceptance: "not run", visualRedaction: "not verified by byte scan", release: {} });
  await rpc("initialize", { protocolVersion: "2025-06-18" });
  // 1. Expand
  const fetched = await call("fetch_page", { url: "https://example.com" });
  proof.fetch = { ok: !fetched.error && /documentation examples/u.test(fetched.data?.markdown ?? "") && fetched.data.title === "Example Domain", credits: fetched.data?.credits };
  // 2. Browse + Vault
  const meta = (await call("vault_item", { id: ITEM })).data;
  proof.item = { savedSites: meta.uris, hasTotp: meta.hasTotp };
  const opened = await call("browse_open", { backend: "cloud", url: "https://expand.ai/login", context: "e2e-expand" });
  const session = opened.data.session;
  const before = await call("browse_snapshot", { session });
  proof.loginPage = { url: before.data.url, hasPasswordField: /password/iu.test(before.text) };
  const shotBefore = await call("browse_screenshot", { session });
  // domain lock, live: the same item must be refused on a page that is not one of its saved sites
  const other = await call("browse_open", { backend: "cloud", url: "https://example.com", context: "expand" });
  const refused = await call("vault_login_with", { session: other.data.session, id: ITEM });
  proof.domainLockLive = { refused: refused.error === true, category: refused.category, message: refused.text };
  const otherStopped = await call("browse_stop", { session: other.data.session });
  proof.release.other = !otherStopped.error && otherStopped.data?.stopped === other.data.session;
  const login = await call("vault_login_with", { session, id: ITEM });
  proof.login = login.data ?? { error: login.text };
  const after = await call("browse_snapshot", { session });
  const shotAfter = await call("browse_screenshot", { session });
  proof.afterLogin = { url: after.data?.url, title: after.data?.title, stillOnLoginForm: (after.data?.elements ?? []).some((/** @type {string} */ row) => /input:password/iu.test(row)), shots: [shotBefore.data?.file, shotAfter.data?.file] };
  proof.afterLogin.authenticatedDashboard = after.data?.url === process.env.E2E_AUTH_URL && after.data?.text?.includes(process.env.E2E_AUTH_MARKER) === true;
  const validShot = (/** @type {any} */ shot) => !shot.error && shot.hasImage && typeof shot.data?.file === "string" && fs.existsSync(shot.data.file) && fs.readFileSync(shot.data.file).subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]));
  proof.screenshots = { before: validShot(shotBefore), after: validShot(shotAfter) };
  const stopped = await call("browse_stop", { session });
  proof.release.primary = !stopped.error && stopped.data?.stopped === session;
  child.stdin.end();
  await new Promise((resolve) => child.once("exit", resolve));

  // 4. Textual leak scan only. Compressed PNG byte scans cannot establish visual redaction.
  const item = JSON.parse(execFileSync(path.join(os.homedir(), ".local/bin/bw"), ["get", "item", ITEM], { encoding: "utf8" })).login;
  const secrets = [item.password, item.username];
  if (secrets.some((s) => typeof s !== "string" || s.length < 3)) throw new Error("leak scan requires nonempty known secrets");
  const forms = secrets.flatMap((s) => [s, encodeURIComponent(s), Buffer.from(s).toString("base64"), JSON.stringify(s).slice(1, -1)]);
  /** @type {string[]} */
  const files = [];
  const walk = (/** @type {string} */ dir) => { for (const entry of fs.readdirSync(dir, { withFileTypes: true })) { const full = path.join(dir, entry.name); if (entry.isDirectory()) walk(full); else if (!full.endsWith(".png")) files.push(full); } };
  walk(home);
  const hits = [];
  for (const [label, content] of [["mcp stdout/stderr", Buffer.from(transcript.join(""))], ...files.map((f) => [path.relative(home, f), fs.readFileSync(f)])]) {
    for (const form of forms) if (/** @type {Buffer} */ (content).includes(form)) hits.push(label);
  }
  proof.leakScan = { scanned: ["mcp stdout/stderr", ...files.map((f) => path.relative(home, f))], forbiddenForms: forms.length, hits };
  const ledgerRows = fs.readFileSync(path.join(home, "ledger.jsonl"), "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l));
  proof.ledger = { hasLogin: ledgerRows.some((r) => r.action === "login_with" && r.item === ITEM && r.domain === "expand.ai"), rows: ledgerRows.length, keysOnly: ledgerRows.every((r) => Object.keys(r).sort().join() === "action,domain,item,ts"), sample: ledgerRows.filter((r) => r.action === "login_with") };
  proof.acceptanceFailures = acceptanceFailures(proof);
  fs.writeFileSync(evidence, `${JSON.stringify(proof, null, 2)}\n`);
  console.log(JSON.stringify(proof, null, 2));
  process.exit(proof.acceptanceFailures.length ? 1 : 0);
})().catch((error) => { console.error(`e2e failed: ${error.message}`); child.kill(); process.exit(1); });
