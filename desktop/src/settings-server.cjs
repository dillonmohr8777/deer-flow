"use strict";

const http = require("node:http");
const { randomBytes, timingSafeEqual } = require("node:crypto");
const fs = require("node:fs/promises");
const path = require("node:path");
const { validateEndpoint } = require("./security.cjs");

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

/**
 * @param {{getEndpoint:()=>string, getFailure:()=>string, getExternal:()=>string|undefined, onConnect:(endpoint:string)=>Promise<void>, onExternal:()=>Promise<void>, onRetry:()=>Promise<void>}} options
 */
async function startSettingsServer({ getEndpoint, getFailure, getExternal, onConnect, onExternal, onRetry }) {
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
        } else {
          res.writeHead(404).end("Not found.");
          return;
        }
        res.setHeader("Content-Type", "text/html; charset=utf-8");
        res.writeHead(200).end(page({ title: "Opening workspace", content: '<p>Your connection is ready.</p><p><a href="/">Connection settings</a></p>' }));
        return;
      }
      if (req.method !== "GET" || !["/", "/error", "/external"].includes(url.pathname)) {
        res.writeHead(404).end("Not found.");
        return;
      }
      const token = `<input type="hidden" name="nonce" value="${nonce}">`;
      let title = "Your workspace, on your Mac.";
      let content = `<p>Connect to your MomoBot workspace. Your OpenAI key stays on the server.</p><form action="/connect" method="post">${token}<label for="endpoint">Workspace URL</label><input id="endpoint" type="url" name="endpoint" value="${escapeHTML(getEndpoint())}" autocomplete="url" required><p class="hint">HTTPS for hosted workspaces. Local development can use localhost.</p><button type="submit">Connect to MomoBot</button></form>`;
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
