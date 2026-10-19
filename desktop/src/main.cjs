"use strict";

const { app, BrowserWindow, Menu, shell, session, dialog, clipboard, net } = require("electron");
const fs = require("node:fs/promises");
const fsSync = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { DEFAULT_ENDPOINT, validateEndpoint, isSameOriginNavigation, safeExternalURL, permittedMediaRequest, rendererPreferences } = require("./security.cjs");
const { startSettingsServer, SECRET_HEADER } = require("./settings-server.cjs");
const { handleArtifactDownload } = require("./artifact-download.cjs");
const { validateUpdateURL, checkForUpdate } = require("./update-check.cjs");
// The local Tools panel drives Dillon's own vault and browser helpers; teammates don't have them.
const toolsEnabled = process.env.MOMOBOT_TOOLS === "1";
const tools = toolsEnabled ? require("./tools/tools.cjs") : undefined;

const smoke = process.argv.includes("--smoke-test");
const workspaceSmoke = smoke && process.argv.includes("--verify-workspace");
const loginSmoke = smoke && process.argv.includes("--verify-login");
const soakIndex = process.argv.indexOf("--soak-minutes");
const soakMinutes = smoke && soakIndex > -1 ? Number(process.argv[soakIndex + 1]) : 0;
// A smoke profile keeps the real persistent session (and allows downloads into <profile>/Downloads)
// so sign-in survival across relaunches can be tested without touching the user's own profile.
const profileIndex = process.argv.indexOf("--smoke-profile");
const smokeProfile = smoke && profileIndex > -1 && process.argv[profileIndex + 1] ? path.resolve(process.argv[profileIndex + 1]) : undefined;
/** @type {string|undefined} */
let updateURL;
/** @type {Electron.BrowserWindow} */
let window;
/** @type {Awaited<ReturnType<typeof startSettingsServer>>} */
let settings;
let endpoint = DEFAULT_ENDPOINT;
let failure = "Check that the MomoBot server is running and this Mac can reach it.";
/** @type {string|undefined} */
let external;
let configured = false;
let stopping = false;
let smokeDirectory;

app.setName("MomoBot");
if (smoke) {
  app.setActivationPolicy("accessory");
  if (smokeProfile) fsSync.mkdirSync(smokeProfile, { recursive: true, mode: 0o700 });
  smokeDirectory = smokeProfile ?? fsSync.mkdtempSync(path.join(os.tmpdir(), "momobot-desktop-smoke-"));
  app.setPath("userData", smokeDirectory);
  app.setPath("sessionData", smokeDirectory);
}

function showLocal(route = "/") {
  if (window && !window.isDestroyed()) void window.loadURL(`${settings.origin}${route}`).catch(() => {});
}

async function openWorkspace() {
  external = undefined;
  try {
    await window.loadURL(endpoint);
  } catch {
    showLocal("/error");
  }
}

/** Silent checks speak up only when a newer release exists. @param {boolean} interactive */
async function checkUpdates(interactive) {
  if (!updateURL) {
    if (interactive) await dialog.showMessageBox(window, { message: "Update checks aren't set up for this copy of MomoBot.", detail: "Reinstall with the team setup command to turn them on." });
    return;
  }
  const result = await checkForUpdate({ updateURL, currentVersion: app.getVersion(), fetchImpl: net.fetch });
  if (result.status === "newer") {
    // The site's setup.sh pins the new release's SHA-256; never the release's own install.sh.
    const command = `curl -fsSL ${updateURL}setup.sh | sh`;
    const { response } = await dialog.showMessageBox(window, {
      message: `MomoBot ${result.latest} is available`,
      detail: `You have ${app.getVersion()}. Paste this into Terminal, then reopen MomoBot:\n\n${command}`,
      buttons: ["Copy Command", "Later"], defaultId: 0, cancelId: 1, noLink: true,
    });
    if (response === 0) clipboard.writeText(command);
  } else if (interactive) {
    await dialog.showMessageBox(window, result.status === "current"
      ? { message: "MomoBot is up to date.", detail: `Version ${app.getVersion()}.` }
      : { type: "warning", message: "Couldn't check for updates.", detail: "Check your internet connection and try again." });
  }
}

/** @param {Electron.Event} event @param {string} target */
function guardNavigation(event, target) {
  if (isSameOriginNavigation(target, endpoint, settings.origin)) return;
  event.preventDefault();
  if (smoke) return;
  external = safeExternalURL(target) ?? undefined;
  if (external) showLocal("/external");
}

/** @param {Electron.Session} partition */
function configureSession(partition) {
  // Only this app's own requests to the local settings server carry the per-launch secret.
  partition.webRequest.onBeforeSendHeaders((details, callback) => {
    const headers = details.requestHeaders;
    if (details.url.startsWith(`${settings.origin}/`)) headers[SECRET_HEADER] = settings.secret;
    callback({ requestHeaders: headers });
  });
  partition.setPermissionCheckHandler((_contents, permission, origin, details) => permittedMediaRequest(permission, origin, endpoint, details));
  partition.setPermissionRequestHandler((_contents, permission, callback, details) => {
    let origin = "";
    try { origin = new URL(details.requestingUrl).origin; } catch { /* Reject unknown documents. */ }
    const mediaTypes = "mediaTypes" in details ? details.mediaTypes : undefined;
    callback(!smoke && permittedMediaRequest(permission, origin, endpoint, { mediaTypes }));
  });
  partition.on("will-download", (event, item, contents, frame) => {
    if ((smoke && !smokeProfile) || !window || window.isDestroyed() || contents !== window.webContents || frame !== contents.mainFrame) {
      event.preventDefault();
      return;
    }
    handleArtifactDownload(event, item, {
      endpoint, documentURL: contents.getURL(), frameURL: frame.url, ownedFrame: true,
      downloadsDirectory: smokeProfile ? path.join(smokeProfile, "Downloads") : app.getPath("downloads"),
      // A smoke profile is an operator-run test with no visible window to confirm in.
      confirm: (filename) => Boolean(smokeProfile) || window.isVisible() && window.isFocused() && dialog.showMessageBoxSync(window, {
        title: "Save MomoBot file", message: `Save ${filename} to Downloads?`,
        buttons: ["Save File", "Cancel"], defaultId: 1, cancelId: 1, noLink: true,
      }) === 0,
    });
  });
}

async function runSmoke() {
  if (workspaceSmoke && loginSmoke) throw new Error("Choose one smoke boundary: workspace or login.");
  if (!(soakMinutes >= 0 && soakMinutes <= 240)) throw new Error("--soak-minutes must be between 0 and 240.");
  /** @type {string[]} */
  const crashes = [];
  window.webContents.on("render-process-gone", (_event, details) => crashes.push(`renderer:${details.reason}`));
  window.webContents.on("unresponsive", () => crashes.push("renderer:unresponsive"));
  app.on("child-process-gone", (_event, details) => crashes.push(`${details.type}:${details.reason}`));
  const memory = () => app.getAppMetrics().reduce((total, metric) => total + metric.memory.workingSetSize, 0);
  await window.loadURL(workspaceSmoke || loginSmoke || soakMinutes ? endpoint : settings.origin);
  const startMemoryKB = memory();
  // Soak: reload the real workspace once a minute and record any crash or hang.
  for (let minute = 0; minute < soakMinutes; minute++) {
    await new Promise((resolve) => setTimeout(resolve, 60_000));
    window.webContents.reload();
  }
  const soak = soakMinutes ? { minutes: soakMinutes, crashes, startMemoryKB, endMemoryKB: memory() } : undefined;
  if (loginSmoke) {
    for (let attempt = 0; attempt < 40; attempt++) {
      if (new URL(window.webContents.getURL()).pathname === "/login" && await window.webContents.executeJavaScript("!!document.querySelector('form') && !!document.querySelector('h1')?.textContent?.trim()").catch(() => false)) break;
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
  }
  const renderer = await window.webContents.executeJavaScript("({require:typeof require,process:typeof process,heading:document.querySelector('h1')?.textContent,form:document.querySelector('form')?.action,hasPassword:!!document.querySelector('input[type=password]'),hasLoginButton:[...document.querySelectorAll('button')].some(button=>/sign in|log in/i.test(button.textContent||''))})");
  const preferences = rendererPreferences();
  const currentURL = window.webContents.getURL();
  await window.webContents.executeJavaScript("window.location.href='https://example.invalid/blocked'");
  await new Promise((resolve) => setTimeout(resolve, 150));
  const blockedNavigation = window.webContents.getURL() === currentURL;
  const processMetric = app.getAppMetrics().find((metric) => metric.pid === window.webContents.getOSProcessId());
  const osSandboxed = processMetric?.sandboxed === true;
  const reachedWorkspace = !workspaceSmoke || renderer.heading === "OpenAI crew";
  const reachedLogin = !loginSmoke || (new URL(currentURL).pathname === "/login" && typeof renderer.heading === "string" && !!renderer.heading.trim() && !!renderer.form);
  // Reported, not gating: an unreachable release server must not fail a launch check.
  const update = updateURL ? await checkForUpdate({ updateURL, currentVersion: app.getVersion(), fetchImpl: net.fetch }) : undefined;
  const passed = crashes.length === 0 && reachedWorkspace && reachedLogin && renderer.require === "undefined" && renderer.process === "undefined" && osSandboxed && preferences.contextIsolation === true && preferences.nodeIntegration === false && preferences.webSecurity === true && blockedNavigation && !window.isVisible();
  process.stdout.write(`${JSON.stringify({ type: "desktop-smoke", passed, workspaceSmoke, loginSmoke, reachedWorkspace, reachedLogin, finalOrigin: new URL(currentURL).origin, soak, update, version: app.getVersion(), electron: process.versions.electron, hidden: !window.isVisible(), osSandboxed, renderer, blockedNavigation })}\n`);
  app.exit(passed ? 0 : 1);
}

app.whenReady().then(async () => {
  const configPath = path.join(app.getPath("userData"), "connection.json");
  try {
    const saved = JSON.parse(await fs.readFile(configPath, "utf8"));
    updateURL = validateUpdateURL(saved.updateURL);
    endpoint = validateEndpoint(saved.endpoint);
    configured = true;
  } catch { /* First launch and invalid configurations use the safe setup screen. */ }
  if (process.env.MOMOBOT_DESKTOP_URL) {
    try {
      endpoint = validateEndpoint(process.env.MOMOBOT_DESKTOP_URL);
      configured = true;
    } catch (error) {
      failure = error instanceof Error ? error.message : "Check your workspace URL.";
      configured = false;
    }
  }
  updateURL = validateUpdateURL(process.env.MOMOBOT_UPDATE_URL) ?? updateURL;
  settings = await startSettingsServer({
    tools,
    getEndpoint: () => endpoint,
    getFailure: () => failure,
    getExternal: () => external,
    onConnect: async (nextEndpoint) => {
      await fs.mkdir(path.dirname(configPath), { recursive: true });
      await fs.writeFile(configPath, `${JSON.stringify({ endpoint: nextEndpoint, updateURL }, null, 2)}\n`, { mode: 0o600 });
      endpoint = nextEndpoint;
      configured = true;
      setImmediate(() => { void openWorkspace(); });
    },
    onRetry: async () => { setImmediate(() => { void openWorkspace(); }); },
    onExternal: async () => {
      const safe = safeExternalURL(external);
      external = undefined;
      if (safe && !smoke) await shell.openExternal(safe);
      setImmediate(() => { void openWorkspace(); });
    },
  });
  const preferences = rendererPreferences();
  if (smoke && !smokeProfile) preferences.partition = `momobot-smoke-${process.pid}`;
  configureSession(session.fromPartition(preferences.partition));
  window = new BrowserWindow({
    width: 1280,
    height: 860,
    minWidth: 390,
    minHeight: 600,
    show: false,
    backgroundColor: "#f2ede3",
    title: "MomoBot",
    autoHideMenuBar: false,
    webPreferences: preferences,
  });
  window.webContents.on("will-navigate", guardNavigation);
  window.webContents.on("will-redirect", guardNavigation);
  window.webContents.on("will-frame-navigate", (details) => {
    if (!details.isMainFrame && !isSameOriginNavigation(details.url, endpoint, settings.origin)) details.preventDefault();
  });
  window.webContents.setWindowOpenHandler(({ url }) => {
    if (!smoke || smokeProfile) {
      if (isSameOriginNavigation(url, endpoint, settings.origin)) setImmediate(() => { void window.loadURL(url); });
      else {
        external = safeExternalURL(url) ?? undefined;
        if (external) setImmediate(() => showLocal("/external"));
      }
    }
    return { action: "deny" };
  });
  window.webContents.on("did-fail-load", (_event, code, _description, url, isMainFrame) => {
    if (isMainFrame && code !== -3 && !url.startsWith(settings.origin)) {
      failure = `MomoBot could not reach the workspace (connection error ${code}). Check the server and your network, then try again.`;
      showLocal("/error");
    }
  });
  window.webContents.on("did-navigate", (_event, url, status) => {
    if (status >= 400 && !url.startsWith(settings.origin)) {
      failure = `The workspace returned HTTP ${status}. Check that the MomoBot workspace is installed on this server.`;
      showLocal("/error");
    }
  });
  /** @type {Electron.MenuItemConstructorOptions[]} */
  const template = [
    { label: "MomoBot", submenu: [{ role: "about" }, { label: "Check for Updates…", click: () => { void checkUpdates(true); } }, { type: "separator" }, { label: "Connection…", click: () => showLocal() }, ...(toolsEnabled ? [{ label: "Tools…", accelerator: "CmdOrCtrl+Shift+T", click: () => showLocal("/tools") }] : []),
      { label: "Open at Login", type: "checkbox", checked: app.getLoginItemSettings().openAtLogin, click: (item) => app.setLoginItemSettings({ openAtLogin: item.checked }) },
      { type: "separator" }, { role: "quit" }] },
    { role: "editMenu" },
    { label: "View", submenu: [{ role: "reload" }, { role: "resetZoom" }, { role: "zoomIn" }, { role: "zoomOut" }, { role: "togglefullscreen" }] },
    { role: "windowMenu" },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
  if (smoke) {
    await runSmoke();
    return;
  }
  window.once("ready-to-show", () => window.show());
  setTimeout(() => { void checkUpdates(false); }, 5_000);
  if (configured) await openWorkspace();
  else await window.loadURL(settings.origin);
}).catch((error) => {
  process.stderr.write(`MomoBot desktop failed to start: ${error.message}\n`);
  app.exit(1);
});

app.on("window-all-closed", () => app.quit());
app.on("before-quit", (event) => {
  if (stopping || !settings) return;
  event.preventDefault();
  stopping = true;
  void Promise.allSettled([tools?.closeAll(), settings.close()]).finally(() => app.quit());
});
