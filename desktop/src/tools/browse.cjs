"use strict";

const { execFile, spawn } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const crypto = require("node:crypto");
const { CDP, Page, sleep } = require("./cdp.cjs");
const { cloudBlocked, hostOf, redact } = require("./policy.cjs");
const ledger = require("./ledger.cjs");
const { PolicyError } = require("./errors.cjs");
// No browser-wide request guard exists yet; no environment override may enable cloud automation.
const CLOUD_AUTOMATION_AVAILABLE = false;

const API = "https://api.browserbase.com/v1";
const WITH_BROWSERBASE = path.join(os.homedir(), ".local", "bin", "with-browserbase");
const AGENTS = path.join(os.homedir(), "code", "_setup", "browser-agents");
const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const PROFILES = path.join(os.homedir(), ".local", "share", "browser-agents", "profiles");
const MAX_SESSIONS = 2;
const TERMINAL = new Set(["COMPLETED", "ERROR", "TIMED_OUT"]);

/** @typedef {{id:string, backend:"cloud"|"local", page:Page, cdp:CDP, secrets:Set<string>, usernames:Set<string>, release:()=>Promise<void>, started:number, label:string}} Session */
/** @type {Map<string, Session>} */
const sessions = new Map();
/** @type {string|undefined} */
let keyCache;
/** @type {string|undefined} */
let projectCache;

/** @param {string} file @param {string[]} args @returns {Promise<string>} */
function run(file, args) {
  return new Promise((resolve, reject) => execFile(file, args, { timeout: 30000, maxBuffer: 1 << 20 }, (error, stdout) => error ? reject(new Error(`${path.basename(file)} failed`)) : resolve(stdout)));
}

/** Browserbase key through the protected launcher (Keychain browserbase.api-key). Held in memory only. */
async function apiKey() {
  keyCache ??= process.env.BROWSERBASE_API_KEY || (await run(WITH_BROWSERBASE, ["printenv", "BROWSERBASE_API_KEY"])).trim();
  if (!keyCache) throw new Error("Browserbase key unavailable (Keychain browserbase.api-key)");
  return keyCache;
}

/** @param {string} method @param {string} route @param {unknown} [body] @returns {Promise<any>} */
async function bb(method, route, body) {
  const response = await fetch(`${API}${route}`, {
    method, headers: { "X-BB-API-Key": await apiKey(), "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(30000),
  });
  if (!response.ok) throw new Error(`Browserbase ${method} ${route.split("?")[0]} failed: HTTP ${response.status}`);
  return response.json();
}

async function projectId() {
  projectCache ??= process.env.BROWSERBASE_PROJECT_ID || (await bb("GET", "/projects"))[0]?.id;
  if (!projectCache) throw new Error("no Browserbase project");
  return projectCache;
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/iu;

/** @param {string} file @returns {Record<string,string>} */
function readJSON(file) { try { return JSON.parse(fs.readFileSync(file, "utf8")); } catch { return {}; } }

/** One persistent context per site: browser-agents' contexts.json (read only) first, then this app's own map. @param {string} name */
async function contextFor(name) {
  if (UUID.test(name)) return name;
  const own = path.join(ledger.home(), "contexts.json");
  const known = { ...readJSON(path.join(AGENTS, "contexts.json")), ...readJSON(own) };
  if (known[name]) return known[name];
  const created = (await bb("POST", "/contexts", { projectId: await projectId() })).id;
  fs.writeFileSync(own, `${JSON.stringify({ ...readJSON(own), [name]: created }, null, 2)}\n`, { mode: 0o600 });
  return created;
}

/** expand.ai -> "expand", app.netlify.com -> "netlify" @param {string} host */
function siteKey(host) { const labels = host.split("."); return labels[Math.max(0, labels.length - 2)] ?? host; }

/** sites.yaml proxy_domains: bot-protected hosts that get the residential proxy and captcha solving. @param {string} host */
function proxyNeeded(host) {
  try {
    const text = fs.readFileSync(path.join(AGENTS, "sites.yaml"), "utf8");
    const block = /^proxy_domains:\s*\n((?:\s+-\s+\S+.*\n)+)/mu.exec(text)?.[1] ?? "";
    return [...block.matchAll(/^\s+-\s+(\S+)/gmu)].some((match) => host === match[1] || host.endsWith(`.${match[1]}`));
  } catch { return false; }
}

/**
 * @param {{url?:string, context?:string, proxies?:boolean, captchas?:boolean, timeout?:number}} options
 * @returns {Promise<Session>}
 */
async function openCloud({ url, context, proxies, captchas, timeout = 600 }) {
  assertInteractiveNavigation({ backend: "cloud" });
  const host = url ? hostOf(url) : null;
  if (url && cloudBlocked(url)) throw new Error("Google, Facebook and Apple are never opened in Browserbase (lockout risk). Use backend \"local\".");
  const contextId = await contextFor(context ?? (host ? siteKey(host) : "scratch"));
  const project = await projectId();
  const running = (await bb("GET", "/sessions?status=RUNNING")).filter((/** @type {any} */ s) => s.contextId === contextId);
  if (running.length) throw new Error("another Browserbase session already holds this login context; stop it first");
  const wantProxy = proxies ?? (host ? proxyNeeded(host) : false);
  const cloud = await bb("POST", "/sessions", {
    projectId: project, timeout: Math.min(Math.max(timeout, 60), 900), keepAlive: false, proxies: wantProxy,
    browserSettings: { context: { id: contextId, persist: true }, recordSession: false, logSession: false, solveCaptchas: captchas ?? wantProxy },
    userMetadata: { agent: "momobot-desktop-tools", run: crypto.randomBytes(4).toString("hex") },
  });
  let cdp;
  try {
    cdp = await CDP.connect(cloud.connectUrl);
    const page = await Page.attach(cdp);
    const connection = cdp;
    const release = async () => {
      connection.close();
      let status = (await bb("GET", `/sessions/${cloud.id}`)).status;
      if (!TERMINAL.has(status)) {
        await bb("POST", `/sessions/${cloud.id}`, { projectId: project, status: "REQUEST_RELEASE" });
        for (let attempt = 0; attempt < 10 && !TERMINAL.has(status); attempt++) { await sleep(700); status = (await bb("GET", `/sessions/${cloud.id}`)).status; }
      }
      if (!TERMINAL.has(status)) throw new Error("Browserbase release unconfirmed; the finite timeout will end it");
    };
    return { id: "", backend: "cloud", page, cdp, secrets: new Set(), usernames: new Set(), release, started: Date.now(), label: `browserbase ${proxies ?? wantProxy ? "proxy" : "direct"}` };
  } catch (error) {
    cdp?.close();
    await bb("POST", `/sessions/${cloud.id}`, { projectId: project, status: "REQUEST_RELEASE" }).catch(() => {});
    throw error;
  }
}

/** Real Chrome on this Mac, one profile per site (the same profile dir browser-agents' trust_device.py uses). @param {{profile:string, headless?:boolean}} options @returns {Promise<Session>} */
async function openLocal({ profile, headless = true }) {
  if (!/^[a-z0-9_-]{1,40}$/u.test(profile)) throw new Error("profile must be a short lowercase name");
  const dir = path.join(PROFILES, profile);
  fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
  const portFile = path.join(dir, "DevToolsActivePort");
  fs.rmSync(portFile, { force: true });
  const flags = ["--no-first-run", "--no-default-browser-check", "--disable-blink-features=AutomationControlled", `--user-data-dir=${dir}`, "--remote-debugging-port=0", "--remote-debugging-address=127.0.0.1"];
  if (headless) {
    const major = (await run(CHROME, ["--version"])).trim().split(" ").pop()?.split(".")[0];
    flags.unshift("--headless=new", `--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/${major}.0.0.0 Safari/537.36`, "--window-size=1366,900");
  }
  const child = spawn(CHROME, [...flags, "about:blank"], { stdio: "ignore" });
  const exited = new Promise((resolve) => child.once("exit", resolve));
  let wsUrl = "";
  for (let attempt = 0; attempt < 150 && !wsUrl; attempt++) {
    if (child.exitCode !== null) throw new Error("Chrome exited early; is this profile already open elsewhere?");
    try { const [port, endpoint] = fs.readFileSync(portFile, "utf8").split("\n"); if (port && endpoint) wsUrl = `ws://127.0.0.1:${port}${endpoint}`; } catch { /* not written yet */ }
    if (!wsUrl) await sleep(200);
  }
  if (!wsUrl) { child.kill(); throw new Error("Chrome did not open a DevTools port"); }
  const cdp = await CDP.connect(wsUrl);
  const page = await Page.attach(cdp);
  const release = async () => {
    await cdp.send("Browser.close").catch(() => {});
    cdp.close();
    await Promise.race([exited, sleep(15000)]);
    if (child.exitCode === null) child.kill();
  };
  return { id: "", backend: "local", page, cdp, secrets: new Set(), usernames: new Set(), release, started: Date.now(), label: `local chrome profile ${profile}` };
}

/** @param {{backend?:"cloud"|"local", url?:string, context?:string, profile?:string, proxies?:boolean, captchas?:boolean, headless?:boolean, timeout?:number}} options */
async function open(options = {}) {
  if (sessions.size >= MAX_SESSIONS) throw new Error(`at most ${MAX_SESSIONS} browser sessions at once; stop one first`);
  const backend = options.backend ?? "cloud";
  assertInteractiveNavigation({ backend });
  const session = backend === "local" ? await openLocal({ profile: options.profile ?? (options.url && hostOf(options.url) ? siteKey(/** @type {string} */ (hostOf(options.url))) : "scratch"), headless: options.headless }) : await openCloud(options);
  session.id = crypto.randomBytes(3).toString("hex");
  sessions.set(session.id, session);
  ledger.record({ action: `browse_open_${backend}`, domain: options.url ? hostOf(options.url) : null });
  if (options.url) await goto(session.id, options.url);
  return { session: session.id, backend: session.label, url: await session.page.url() };
}

/** @param {string} id @returns {Session} */
function get(id) {
  const session = sessions.get(id);
  if (!session) throw new Error(`no browser session ${id}; open one first`);
  return session;
}

/** @param {string} id @param {string} url */
async function goto(id, url) {
  const session = get(id);
  assertInteractiveNavigation(session);
  const host = hostOf(url);
  if (!host) throw new Error("only plain http(s) URLs without embedded credentials can be opened");
  if (session.backend === "cloud" && cloudBlocked(url)) throw new Error("Google, Facebook and Apple are never opened in Browserbase (lockout risk). Open a local session instead.");
  await session.page.goto(url);
  const landed = await session.page.url();
  if (session.backend === "cloud" && cloudBlocked(landed)) { await session.page.goto("about:blank"); throw new Error("the page redirected to Google, Facebook or Apple, which are never used from Browserbase; returned to a blank page"); }
  return { url: landed.split(/[?#]/u)[0] };
}

// Tags every visible interactive element with data-mb-ref and describes it. Input values are never read.
const TAG = `(() => {
  document.querySelectorAll('[data-mb-ref]').forEach((e) => e.removeAttribute('data-mb-ref'));
  const rows = []; let n = 0;
  for (const el of document.querySelectorAll('a[href],button,input,select,textarea,summary,[role=button],[role=link],[role=checkbox],[onclick]')) {
    const r = el.getBoundingClientRect(); const cs = getComputedStyle(el);
    if (r.width < 1 || r.height < 1 || cs.visibility === 'hidden' || cs.display === 'none' || el.disabled) continue;
    el.setAttribute('data-mb-ref', ++n);
    const tag = el.tagName.toLowerCase(); const type = (el.type || el.getAttribute('type') || '').toLowerCase();
    const label = (el.getAttribute('aria-label') || (tag === 'input' && !['submit', 'button'].includes(type) ? '' : (el.innerText || el.value)) || el.getAttribute('placeholder') || el.getAttribute('title') || '').trim().replace(/\\s+/g, ' ').slice(0, 80);
    let href = ''; try { if (el.href) { const u = new URL(el.href); href = u.host + u.pathname; } } catch (e) {}
    let action = ''; try { if (el.form) action = new URL(el.hasAttribute('formaction') && type === 'submit' ? el.formAction : el.form.action, document.baseURI).href; } catch (e) {}
    const form = el.form ? Array.from(document.forms).indexOf(el.form) : null;
    rows.push({ ref: n, tag, type, label, name: el.getAttribute('name') || el.id || '', ac: el.getAttribute('autocomplete') || '', placeholder: el.getAttribute('placeholder') || '', href, action, form });
  }
  return { title: document.title, text: (document.body ? document.body.innerText : '').replace(/[ \\t]+/g, ' ').replace(/\\n{3,}/g, '\\n\\n').slice(0, 4000), rows };
})()`;

/** @param {string} id @returns {Promise<{title:string, text:string, rows:any[]}>} */
async function tagged(id) { const session = get(id); assertInteractiveNavigation(session); return session.page.eval(TAG); }

/** @param {string} id */
async function snapshot(id) {
  const session = get(id);
  assertInteractiveNavigation(session);
  const { title, text, rows } = await tagged(id);
  const lines = rows.map((row) => `[${row.ref}] ${row.tag}${row.type ? `:${row.type}` : ""} ${JSON.stringify(row.label || row.placeholder || row.name)}${row.href ? ` -> ${row.href}` : ""}`);
  return redact({ url: (await session.page.url()).split(/[?#]/u)[0], title, elements: lines, text }, session.secrets);
}

/** Fail closed: DOM inspection cannot predict JS, delayed redirects or popup navigation.
 * Until a browser-wide request guard covers every target, cloud input that can
 * trigger navigation is unavailable, including focus, text and DOM evaluation.
 * All cloud automation is disabled before session creation; existing sessions may only be released.
 * @param {{backend:"cloud"|"local"}} session
 */
function assertInteractiveNavigation(session) {
  if (session.backend === "cloud" && !CLOUD_AUTOMATION_AVAILABLE) throw new PolicyError("CLOUD_UNAVAILABLE", "Cloud automation is unavailable until every navigation target has a request-level protected-site guard. Use a local session.");
}

/** @param {string} id @param {number} ref */
async function click(id, ref) { assertInteractiveNavigation(get(id)); await get(id).page.click(ref); await sleep(600); return { url: (await get(id).page.url()).split(/[?#]/u)[0] }; }

/** Plain (non-secret) text. Secrets only ever go through the vault tools. @param {string} id @param {number} ref @param {string} text */
async function fill(id, ref, text) { const session = get(id); assertInteractiveNavigation(session); const { page } = session; await page.focus(ref); await page.insert(text); return { ok: true }; }

/** @param {string} id @param {"Enter"|"Tab"|"Escape"} key */
async function press(id, key) { assertInteractiveNavigation(get(id)); await get(id).page.press(key); await sleep(600); return { url: (await get(id).page.url()).split(/[?#]/u)[0] }; }

/** Blur every input and any text showing a username used in this session, capture, then restore. */
/** @param {string} id */
async function screenshot(id) {
  const session = get(id);
  assertInteractiveNavigation(session);
  const names = JSON.stringify([...session.usernames].filter((name) => name.length >= 3));
  await session.page.eval(`(() => {
    const s = document.createElement('style'); s.id = 'mb-mask'; s.textContent = 'input,textarea,select,[contenteditable]{filter:blur(8px)!important}'; document.head.appendChild(s);
    const names = ${names}; const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let n = w.nextNode(); n; n = w.nextNode()) if (n.parentElement && names.some((x) => n.textContent.includes(x))) { n.parentElement.setAttribute('data-mb-mask', '1'); n.parentElement.style.setProperty('filter', 'blur(8px)', 'important'); }
  })()`);
  let png;
  try { png = await session.page.screenshot(); } finally {
    await session.page.eval(`(() => { document.getElementById('mb-mask')?.remove(); document.querySelectorAll('[data-mb-mask]').forEach((e) => { e.style.removeProperty('filter'); e.removeAttribute('data-mb-mask'); }); })()`).catch(() => {});
  }
  const dir = path.join(ledger.home(), "shots");
  fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
  const name = `${new Date().toISOString().replace(/[:.]/gu, "-")}-${id}.png`;
  fs.writeFileSync(path.join(dir, name), png, { mode: 0o600 });
  return { file: path.join(dir, name), name, base64: png.toString("base64") };
}

/** @param {string} id */
async function stop(id) {
  const session = get(id);
  sessions.delete(id);
  await session.release();
  return { stopped: id };
}

async function closeAll() { await Promise.allSettled([...sessions.keys()].map(stop)); }

function list() { return [...sessions.values()].map((s) => ({ session: s.id, backend: s.label, ageSeconds: Math.round((Date.now() - s.started) / 1000) })); }

module.exports = { open, goto, snapshot, click, fill, press, screenshot, stop, closeAll, list, get, tagged, sessions, assertInteractiveNavigation, CLOUD_AUTOMATION_AVAILABLE };
