"use strict";

const { app, BrowserWindow, Menu, shell, session, dialog } = require("electron");
const fs = require("node:fs/promises");
const fsSync = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { DEFAULT_ENDPOINT, validateEndpoint, isSameOriginNavigation, safeExternalURL, permittedMediaRequest, rendererPreferences } = require("./security.cjs");
const { startSettingsServer } = require("./settings-server.cjs");
const { handleArtifactDownload } = require("./artifact-download.cjs");

const smoke = process.argv.includes("--smoke-test");
const workspaceSmoke = smoke && process.argv.includes("--verify-workspace");
const loginSmoke = smoke && process.argv.includes("--verify-login");
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
  smokeDirectory = fsSync.mkdtempSync(path.join(os.tmpdir(), "momobot-desktop-smoke-"));
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
  partition.setPermissionCheckHandler((_contents, permission, origin, details) => permittedMediaRequest(permission, origin, endpoint, details));
  partition.setPermissionRequestHandler((_contents, permission, callback, details) => {
    let origin = "";
    try { origin = new URL(details.requestingUrl).origin; } catch { /* Reject unknown documents. */ }
    const mediaTypes = "mediaTypes" in details ? details.mediaTypes : undefined;
    callback(!smoke && permittedMediaRequest(permission, origin, endpoint, { mediaTypes }));
  });
  partition.on("will-download", (event, item, contents, frame) => {
    if (smoke || !window || window.isDestroyed() || contents !== window.webContents || frame !== contents.mainFrame) {
      event.preventDefault();
      return;
    }
    handleArtifactDownload(event, item, {
      endpoint, documentURL: contents.getURL(), frameURL: frame.url, ownedFrame: true,
      downloadsDirectory: app.getPath("downloads"),
      confirm: (filename) => window.isVisible() && window.isFocused() && dialog.showMessageBoxSync(window, {
        title: "Save MomoBot file", message: `Save ${filename} to Downloads?`,
        buttons: ["Save File", "Cancel"], defaultId: 1, cancelId: 1, noLink: true,
      }) === 0,
    });
  });
}

async function runSmoke() {
  if (workspaceSmoke && loginSmoke) throw new Error("Choose one smoke boundary: workspace or login.");
  await window.loadURL(workspaceSmoke || loginSmoke ? endpoint : settings.origin);
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
  const passed = reachedWorkspace && reachedLogin && renderer.require === "undefined" && renderer.process === "undefined" && osSandboxed && preferences.contextIsolation === true && preferences.nodeIntegration === false && preferences.webSecurity === true && blockedNavigation && !window.isVisible();
  process.stdout.write(`${JSON.stringify({ type: "desktop-smoke", passed, workspaceSmoke, loginSmoke, reachedWorkspace, reachedLogin, version: app.getVersion(), electron: process.versions.electron, hidden: !window.isVisible(), osSandboxed, renderer, blockedNavigation })}\n`);
  app.exit(passed ? 0 : 1);
}

app.whenReady().then(async () => {
  const configPath = path.join(app.getPath("userData"), "connection.json");
  try {
    const saved = JSON.parse(await fs.readFile(configPath, "utf8"));
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
  settings = await startSettingsServer({
    getEndpoint: () => endpoint,
    getFailure: () => failure,
    getExternal: () => external,
    onConnect: async (nextEndpoint) => {
      await fs.mkdir(path.dirname(configPath), { recursive: true });
      await fs.writeFile(configPath, `${JSON.stringify({ endpoint: nextEndpoint }, null, 2)}\n`, { mode: 0o600 });
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
  if (smoke) preferences.partition = `momobot-smoke-${process.pid}`;
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
    if (!smoke) {
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
      failure = `The workspace returned HTTP ${status}. Check that the OpenAI workspace is installed on this server.`;
      showLocal("/error");
    }
  });
  /** @type {Electron.MenuItemConstructorOptions[]} */
  const template = [
    { label: "MomoBot", submenu: [{ label: "Connection…", click: () => showLocal() }, { type: "separator" }, { role: "quit" }] },
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
  void settings.close().finally(() => app.quit());
});
