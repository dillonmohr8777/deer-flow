"use strict";

// Stdio MCP server for MomoBot Desktop Tools. Register it with any agent:
//   { "command": "node", "args": ["<app>/src/tools/mcp-server.cjs"] }
// Newline-delimited JSON-RPC 2.0. Tool errors are returned as tool results, never as stack traces.
const readline = require("node:readline");
const tools = require("./tools.cjs");
const { errorCategory } = require("./errors.cjs");
const { redact } = require("./policy.cjs");

/** @param {any} message */
function send(message) { process.stdout.write(`${JSON.stringify(message)}\n`); }

/** @param {any} request */
async function handle(request) {
  const { id, method, params } = request;
  if (id === undefined) return; // notifications need no reply
  try {
    if (method === "initialize") {
      send({ jsonrpc: "2.0", id, result: { protocolVersion: params?.protocolVersion ?? "2025-06-18", capabilities: { tools: {} }, serverInfo: { name: "momobot-desktop-tools", version: "0.3.0" } } });
    } else if (method === "tools/list") {
      send({ jsonrpc: "2.0", id, result: { tools: tools.TOOLS.map((tool) => ({ name: tool.name, description: tool.description, inputSchema: tools.jsonSchema(tool) })) } });
    } else if (method === "tools/call") {
      const content = [];
      let isError = false;
      let category;
      try {
        const name = String(params?.name);
        const { _image, ...result } = await tools.run(name, params?.arguments ?? {});
        content.push({ type: "text", text: JSON.stringify(result, null, 2) });
        if (_image) content.push({ type: "image", data: _image, mimeType: "image/png" });
      } catch (error) {
        isError = true;
        category = errorCategory(error);
        content.push({ type: "text", text: redact(error instanceof Error ? error.message : "tool failed", tools.secrets()) });
      }
      send({ jsonrpc: "2.0", id, result: { content, isError, ...(category ? { errorCategory: category } : {}) } });
    } else if (method === "ping") {
      send({ jsonrpc: "2.0", id, result: {} });
    } else {
      send({ jsonrpc: "2.0", id, error: { code: -32601, message: "Method not found" } });
    }
  } catch {
    send({ jsonrpc: "2.0", id, error: { code: -32603, message: "Internal error" } });
  }
}

let chain = Promise.resolve();
readline.createInterface({ input: process.stdin }).on("line", (line) => {
  let request;
  try { request = JSON.parse(line); } catch { return; }
  chain = chain.then(() => handle(request)); // one call at a time: sessions are stateful
}).on("close", () => { void chain.then(() => tools.closeAll()).finally(() => process.exit(0)); });
for (const signal of /** @type {const} */ (["SIGTERM", "SIGINT"])) process.on(signal, () => { void tools.closeAll().finally(() => process.exit(0)); });
