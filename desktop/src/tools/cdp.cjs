"use strict";

// Minimal Chrome DevTools Protocol client. It never logs a command or its parameters: Input.insertText carries secrets.

class CDP {
  /** @param {WebSocket} ws */
  constructor(ws) {
    this.ws = ws;
    this.nextId = 0;
    /** @type {Map<number, {method:string, resolve:(value:any)=>void, reject:(error:Error)=>void}>} */
    this.pending = new Map();
    ws.addEventListener("message", (event) => {
      const message = JSON.parse(String(event.data));
      const waiting = message.id && this.pending.get(message.id);
      if (!waiting) return;
      this.pending.delete(message.id);
      if (message.error) waiting.reject(new Error(`${waiting.method} failed: ${String(message.error.message).slice(0, 120)}`));
      else waiting.resolve(message.result);
    });
    ws.addEventListener("close", () => {
      for (const waiting of this.pending.values()) waiting.reject(new Error("browser connection closed"));
      this.pending.clear();
    });
  }

  /** @param {string} url @returns {Promise<CDP>} */
  static connect(url) {
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(url);
      const timer = setTimeout(() => reject(new Error("browser connection timed out")), 30000);
      ws.addEventListener("open", () => { clearTimeout(timer); resolve(new CDP(ws)); });
      ws.addEventListener("error", () => { clearTimeout(timer); reject(new Error("browser connection failed")); });
    });
  }

  /** @param {string} method @param {Record<string, unknown>} [params] @param {string} [sessionId] @returns {Promise<any>} */
  send(method, params = {}, sessionId) {
    const id = ++this.nextId;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { this.pending.delete(id); reject(new Error(`${method} timed out`)); }, 45000);
      this.pending.set(id, { method, resolve: (value) => { clearTimeout(timer); resolve(value); }, reject: (error) => { clearTimeout(timer); reject(error); } });
      this.ws.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
    });
  }

  close() { try { this.ws.close(); } catch { /* already closed */ } }
}

const sleep = (/** @type {number} */ ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** One page target driven over a flattened CDP session. */
class Page {
  /** @param {CDP} cdp @param {string} targetId @param {string} sessionId */
  constructor(cdp, targetId, sessionId) { this.cdp = cdp; this.targetId = targetId; this.sessionId = sessionId; }

  /** @param {CDP} cdp */
  static async attach(cdp) {
    const { targetInfos } = await cdp.send("Target.getTargets");
    let target = targetInfos.find((/** @type {any} */ info) => info.type === "page");
    if (!target) target = { targetId: (await cdp.send("Target.createTarget", { url: "about:blank" })).targetId };
    const { sessionId } = await cdp.send("Target.attachToTarget", { targetId: target.targetId, flatten: true });
    const page = new Page(cdp, target.targetId, sessionId);
    await page.cdp.send("Page.enable", {}, sessionId);
    return page;
  }

  /** @param {string} method @param {Record<string, unknown>} [params] */
  send(method, params) { return this.cdp.send(method, params, this.sessionId); }

  /** Current URL as the browser reports it, not as page script claims. */
  async url() {
    const { targetInfo } = await this.cdp.send("Target.getTargetInfo", { targetId: this.targetId });
    return String(targetInfo.url);
  }

  /** @param {string} expression @returns {Promise<any>} */
  async eval(expression) {
    const result = await this.send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    if (result.exceptionDetails) throw new Error("page script failed");
    return result.result?.value;
  }

  /** @param {string} url */
  async goto(url) {
    const { errorText } = await this.send("Page.navigate", { url });
    if (errorText) throw new Error(`navigation failed: ${errorText}`);
    await this.settle();
  }

  async settle(timeoutMs = 30000) {
    const end = Date.now() + timeoutMs;
    await sleep(400);
    while (Date.now() < end) {
      if (await this.eval("document.readyState").catch(() => "") === "complete") return;
      await sleep(250);
    }
  }

  /** Real mouse click at the centre of the tagged element. @param {number} ref */
  async click(ref) {
    const box = await this.eval(`(() => { const e = document.querySelector('[data-mb-ref="${Number(ref)}"]'); if (!e) return null; e.scrollIntoView({block:'center'}); const r = e.getBoundingClientRect(); return {x: r.left + r.width / 2, y: r.top + r.height / 2}; })()`);
    if (!box) throw new Error(`no element with ref ${ref}; take a fresh snapshot`);
    for (const type of ["mouseMoved", "mousePressed", "mouseReleased"]) {
      await this.send("Input.dispatchMouseEvent", { type, x: box.x, y: box.y, button: type === "mouseMoved" ? "none" : "left", clickCount: type === "mouseMoved" ? 0 : 1 });
    }
  }

  /** Focus an input and select its content, so the next insert replaces it. @param {number} ref */
  async focus(ref) {
    const ok = await this.eval(`(() => { const e = document.querySelector('[data-mb-ref="${Number(ref)}"]'); if (!e) return false; e.scrollIntoView({block:'center'}); e.focus(); if (e.select) e.select(); return document.activeElement === e; })()`);
    if (!ok) throw new Error(`could not focus ref ${ref}; take a fresh snapshot`);
  }

  /** Type text into the focused field. Text rides only on this one CDP command. @param {string} text */
  async insert(text) { await this.send("Input.insertText", { text }); }

  /** @param {"Enter"|"Tab"|"Escape"} key */
  async press(key) {
    const codes = { Enter: { vk: 13, text: "\r" }, Tab: { vk: 9, text: "" }, Escape: { vk: 27, text: "" } }[key];
    if (!codes) throw new Error("unsupported key");
    await this.send("Input.dispatchKeyEvent", { type: codes.text ? "keyDown" : "rawKeyDown", key, code: key, windowsVirtualKeyCode: codes.vk, text: codes.text });
    await this.send("Input.dispatchKeyEvent", { type: "keyUp", key, code: key, windowsVirtualKeyCode: codes.vk });
  }

  /** @returns {Promise<Buffer>} */
  async screenshot() {
    const { data } = await this.send("Page.captureScreenshot", { format: "png" });
    return Buffer.from(data, "base64");
  }
}

module.exports = { CDP, Page, sleep };
