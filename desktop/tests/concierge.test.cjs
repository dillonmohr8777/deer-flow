"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { test } = require("node:test");
process.env.MOMOBOT_TOOLS_HOME = fs.mkdtempSync(path.join(os.tmpdir(), "momobot-concierge-"));
const tools = require("../src/tools/tools.cjs");

const fake = path.join(process.env.MOMOBOT_TOOLS_HOME, "fake.cjs");
fs.writeFileSync(fake, 'const a=process.argv.slice(2);if(a.includes("boom")){console.error("SECRET-pw-123");process.exit(1)}if(a.includes("garbage")){console.log("SECRET-pw-123 not json");process.exit(0)}console.log(JSON.stringify({ok:true,argv:a,live_url:"https://live.example/x"}));');
process.env.MOMO_CONCIERGE_CMD = JSON.stringify([process.execPath, fake]);

test("concierge tools are registered with the asker required", () => {
  const req = tools.TOOLS.find((t) => t.name === "concierge_request");
  assert.equal(req.input.asker.required, true);
  assert.ok(tools.TOOLS.some((t) => t.name === "concierge_status"));
  assert.deepEqual(tools.jsonSchema(req).required, ["asker"]);
});

test("concierge_request relays arguments and returns the reply untouched", async () => {
  const r = await tools.run("concierge_request", { asker: "UAK3WSY15", text: "get me into Bar Crawl wordpress", handoff: "false" });
  assert.deepEqual(r.argv, ["request", "--who", "UAK3WSY15", "--text", "get me into Bar Crawl wordpress", "--no-handoff"]);
  assert.equal(r.live_url, "https://live.example/x");
  assert.deepEqual((await tools.run("concierge_status", { asker: "U1" })).argv, ["status", "--who", "U1"]);
});

test("concierge_request needs an asker, and failures never echo raw output", async () => {
  await assert.rejects(tools.run("concierge_request", { text: "x" }), /needs asker/u);
  for (const text of ["boom", "garbage"]) {
    await assert.rejects(tools.run("concierge_request", { asker: "U1", text }), (e) => !/SECRET-pw-123/u.test(e.message) && /concierge/u.test(e.message));
  }
});
