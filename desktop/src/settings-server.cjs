"use strict";

const http = require("node:http");
const { randomBytes, timingSafeEqual } = require("node:crypto");
const fs = require("node:fs/promises");
const path = require("node:path");
const { validateEndpoint } = require("./security.cjs");
const { redact } = require("./tools/policy.cjs");
const ledger = require("./tools/ledger.cjs");

/** @param {unknown} value */
function escapeHTML(value) {
  return String(value).replace(/[&<>"']/gu, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char] ?? char);
}

/** @param {string|null} actual @param {string} expected */
function matchingNonce(actual, expected) {
  if (typeof actual !== "string") return false;
  const a = Buffer.from(actual);
  const b = Buffer.from(expected);
  return a.length === b.length && timingSafeEqual(a, b);
}

/** @param {{title:string, content:string}} options */
function page({ title, content }) {
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${escapeHTML(title)} · MomoBot</title><link rel="stylesheet" href="/setup.css"></head><body><main><img class="mark" src="/icon.png" width="72" height="72" alt="MomoBot"><p class="eyebrow">MOMENTUM · MOMOBOT</p><h1>${escapeHTML(title)}</h1>${content}</main></body></html>`;
}

/** @param {NonNullable<Parameters<typeof startSettingsServer>[0]["tools"]>} tools @param {string} token */
function toolsPage(tools, token) {
  const sessions = tools.sessions();
  const recent = ledger.read().slice(-8).reverse();
  const forms = tools.TOOLS.map((tool) => {
    const fields = Object.entries(tool.input).map(([key, field]) => {
      const control = field.enum
        ? `<select name="f_${key}" id="${tool.name}-${key}">${field.required ? "" : "<option value=\"\"></option>"}${field.enum.map((value) => `<option>${escapeHTML(value)}</option>`).join("")}</select>`
        : `<input id="${tool.name}-${key}" name="f_${key}" type="text" autocomplete="off"${field.required ? " required" : ""}>`;
      return `<label for="${tool.name}-${key}">${escapeHTML(key)}${field.required ? "" : " (optional)"}</label>${control}<p class="hint">${escapeHTML(field.description)}</p>`;
    }).join("");
    return `<details><summary>${escapeHTML(tool.name)}</summary><p class="hint">${escapeHTML(tool.description)}</p><form action="/tools/run" method="post">${token}<input type="hidden" name="tool" value="${tool.name}">${fields}<button type="submit">Run ${escapeHTML(tool.name)}</button></form></details>`;
  }).join("");
  const open = sessions.length ? sessions.map((s) => `<li>${escapeHTML(s.session)} · ${escapeHTML(s.backend)} · ${s.ageSeconds}s</li>`).join("") : "<li>No browser sessions open.</li>";
  const used = recent.length ? recent.map((r) => `<li>${escapeHTML(r.ts.slice(11, 19))} · ${escapeHTML(r.action)}${r.domain ? ` · ${escapeHTML(r.domain)}` : ""}${r.item ? ` · item ${escapeHTML(r.item.slice(0, 8))}` : ""}</li>`).join("") : "<li>Nothing used yet.</li>";
  return `<p>Browse, fetch, the vault and login codes, on this Mac. Secrets are read locally and redacted from tool output. In cloud sessions, secret text is transmitted over CDP to the Browserbase-hosted browser. Input masking and byte scans do not prove visual redaction. All cloud automation, including opening sessions, navigation, text input and DOM capture, is unavailable pending a browser-wide request-level navigation guard. Local tools remain available.</p><h2>Open sessions</h2><ul>${open}</ul><h2>Recent use</h2><ul>${used}</ul><h2>Tools</h2>${forms}<p><a href="/">Connection settings</a></p>`;
}

/**
 * @param {{getEndpoint:()=>string, getFailure:()=>string, getExternal:()=>string|undefined, onConnect:(endpoint:string)=>Promise<void>, onExternal:()=>Promise<void>, onRetry:()=>Promise<void>, tools?: typeof import("./tools/tools.cjs")}} options
 */
async function startSettingsServer({ getEndpoint, getFailure, getExternal, onConnect, onExternal, onRetry, tools }) {
  const nonce = randomBytes(32).toString("hex");
  let origin = "";
  const server = http.createServer(async (req, res) => {
    res.setHeader("Content-Security-Policy", "default-src 'none'; img-src 'self'; style-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'");
    res.setHeader("Cache-Control", "no-store");
    res.setHeader("X-Content-Type-Options", "nosniff");
    res.setHeader("Referrer-Policy", "no-referrer");
    if (req.headers.host !== new URL(origin).host) {
      res.writeHead(403).end("Invalid host.");
      return;
    }
    const url = new URL(req.url ?? "/", origin);
    try {
      if (req.method === "GET" && ["/setup.css", "/icon.png"].includes(url.pathname)) {
        const file = url.pathname === "/setup.css" ? path.join(__dirname, "../ui/setup.css") : path.join(__dirname, "../assets/icon.png");
        const bytes = await fs.readFile(file);
        res.setHeader("Content-Type", url.pathname.endsWith("css") ? "text/css; charset=utf-8" : "image/png");
        res.writeHead(200).end(bytes);
        return;
      }
      if (req.method === "GET" && tools && url.pathname.startsWith("/tools/shot/")) {
        const name = url.pathname.slice("/tools/shot/".length);
        if (!/^[\w.-]{1,80}\.png$/u.test(name)) { res.writeHead(404).end("Not found."); return; }
        res.setHeader("Content-Type", "image/png");
        res.writeHead(200).end(await fs.readFile(path.join(ledger.home(), "shots", name)));
        return;
      }
      if (req.method === "POST") {
        if (req.headers.origin !== origin || req.headers["content-type"]?.split(";")[0] !== "application/x-www-form-urlencoded") {
          res.writeHead(403).end("Invalid request origin.");
          return;
        }
        let body = "";
        for await (const chunk of req) {
          body += chunk.toString("utf8");
          if (Buffer.byteLength(body) > 4096) {
            res.writeHead(413).end("Request too large.");
            return;
          }
        }
        const form = new URLSearchParams(body);
        if (!matchingNonce(form.get("nonce"), nonce)) {
          res.writeHead(403).end("Invalid form token.");
          return;
        }
        if (url.pathname === "/connect") {
          const endpoint = validateEndpoint(form.get("endpoint"));
          await onConnect(endpoint);
        } else if (url.pathname === "/retry") {
          await onRetry();
        } else if (url.pathname === "/open-external") {
          await onExternal();
        } else if (url.pathname === "/tools/run" && tools) {
          const name = form.get("tool") ?? "";
          const args = Object.fromEntries([...form.entries()].filter(([key, value]) => key.startsWith("f_") && value !== "").map(([key, value]) => [key.slice(2), value]));
          let body;
          try {
            const { _image, ...result } = await tools.run(name, args);
            body = `<pre>${escapeHTML(JSON.stringify(result, null, 2))}</pre>${_image && result.name ? `<img src="/tools/shot/${escapeHTML(result.name)}" alt="Screenshot" style="max-width:100%">` : ""}`;
          } catch (error) {
            body = `<p>${escapeHTML(redact(error instanceof Error ? error.message : "Tool failed.", tools.secrets()))}</p>`;
          }
          res.setHeader("Content-Type", "text/html; charset=utf-8");
          res.writeHead(200).end(page({ title: name, content: `${body}<p><a href="/tools">Back to Tools</a></p>` }));
          return;
        } else {
          res.writeHead(404).end("Not found.");
          return;
        }
        res.setHeader("Content-Type", "text/html; charset=utf-8");
        res.writeHead(200).end(page({ title: "Opening workspace", content: '<p>Your connection is ready.</p><p><a href="/">Connection settings</a></p>' }));
        return;
      }
      if (req.method === "GET" && tools && url.pathname === "/tools") {
        res.setHeader("Content-Type", "text/html; charset=utf-8");
        res.writeHead(200).end(page({ title: "Tools", content: toolsPage(tools, `<input type="hidden" name="nonce" value="${nonce}">`) }));
        return;
      }
      if (req.method !== "GET" || !["/", "/error", "/external"].includes(url.pathname)) {
        res.writeHead(404).end("Not found.");
        return;
      }
      const token = `<input type="hidden" name="nonce" value="${nonce}">`;
      let title = "Your workspace, on your Mac.";
      let content = `<p>Connect to your MomoBot workspace. Your agency credentials stay on the server.</p><form action="/connect" method="post">${token}<label for="endpoint">Workspace URL</label><input id="endpoint" type="url" name="endpoint" value="${escapeHTML(getEndpoint())}" autocomplete="url" required><p class="hint">HTTPS for hosted workspaces. Local development can use localhost.</p><button type="submit">Connect to MomoBot</button></form>`;
      if (url.pathname === "/error") {
        title = "Your workspace couldn't connect.";
        content = `<p>${escapeHTML(getFailure())}</p><p class="endpoint">${escapeHTML(getEndpoint())}</p><form action="/retry" method="post">${token}<button type="submit">Try again</button></form><p><a href="/">Change workspace URL</a></p>`;
      }
      if (url.pathname === "/external") {
        title = "Open this link in your browser?";
        content = `<p>MomoBot keeps other websites outside your workspace.</p><p class="endpoint">${escapeHTML(getExternal() ?? "Link expired")}</p>${getExternal() ? `<form action="/open-external" method="post">${token}<button type="submit">Open in browser</button></form>` : ""}<form action="/retry" method="post">${token}<button class="secondary" type="submit">Return to workspace</button></form>`;
      }
      res.setHeader("Content-Type", "text/html; charset=utf-8");
      res.writeHead(200).end(page({ title, content }));
    } catch (error) {
      res.setHeader("Content-Type", "text/html; charset=utf-8");
      res.writeHead(400).end(page({ title: "Check your connection", content: `<p>${escapeHTML(error instanceof Error ? error.message : "Unable to save connection.")}</p><p><a href="/">Return to connection settings</a></p>` }));
    }
  });
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => resolve(undefined));
  });
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("Unable to start local connection settings.");
  origin = `http://127.0.0.1:${address.port}`;
  return { origin, close: () => new Promise((resolve, reject) => server.close((error) => error ? reject(error) : resolve(undefined))) };
}

module.exports = { startSettingsServer, escapeHTML, matchingNonce };
