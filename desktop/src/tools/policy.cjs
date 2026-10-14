"use strict";

// Sites whose logins must never be driven from a Browserbase cloud browser (lockout risk) and are never auto-filled.
const CLOUD_BLOCKED = ["google.com", "gmail.com", "youtube.com", "facebook.com", "fb.com", "messenger.com", "apple.com", "icloud.com"];
const MIN_SECRET = 3;

/** @param {string} host */
function normHost(host) {
  return host.toLowerCase().replace(/\.$/u, "").replace(/^www\./u, "");
}

/** @param {string} host @param {string} domain */
function isUnder(host, domain) {
  return host === domain || host.endsWith(`.${domain}`);
}

/** Host of a page or saved URI. Bitwarden URIs may omit the scheme; app URIs (androidapp://) have no web host. */
/** @param {string} value @returns {string|null} */
function hostOf(value) {
  try {
    const url = new URL(/^[a-z][a-z0-9+.-]*:\/\//iu.test(value) ? value : `https://${value}`);
    if (!/^https?:$/u.test(url.protocol) || url.username || url.password || !url.hostname) return null;
    return normHost(url.hostname);
  } catch {
    return null;
  }
}

/**
 * Domain lock: may this item's secrets be typed into this page? Only https, and only when the page host equals
 * or is a subdomain of a host saved on the item. Returns the matched saved host (what the ledger records).
 * @param {string} pageUrl @param {readonly string[]} savedUris
 * @returns {{ok:true, domain:string}|{ok:false, reason:string}}
 */
function domainLock(pageUrl, savedUris) {
  let page;
  try { page = new URL(pageUrl); } catch { return { ok: false, reason: "page URL unreadable" }; }
  if (page.protocol !== "https:" || page.username || page.password) return { ok: false, reason: "page is not plain https" };
  const host = normHost(page.hostname);
  const saved = savedUris.map(hostOf).filter((value) => value !== null);
  if (!saved.length) return { ok: false, reason: "item has no saved website to match" };
  const hit = saved.find((domain) => isUnder(host, domain));
  return hit ? { ok: true, domain: hit } : { ok: false, reason: `${host} does not match the item's saved sites` };
}

/** @param {string} url */
function cloudBlocked(url) {
  const host = hostOf(url);
  return host !== null && CLOUD_BLOCKED.some((domain) => isUnder(host, domain));
}

/** @param {string} secret */
function variants(secret) {
  const forms = new Set([secret, encodeURIComponent(secret), JSON.stringify(secret).slice(1, -1), Buffer.from(secret).toString("base64")]);
  return [...forms].filter((form) => form.length >= MIN_SECRET);
}

/**
 * Remove known secrets (and their URL-, JSON- and base64 forms) from any string or JSON-like value.
 * Secrets shorter than 3 characters are not replaced, so a stray character cannot shred ordinary output.
 * @param {unknown} value @param {Iterable<string>} secrets @returns {any}
 */
function redact(value, secrets) {
  const list = [...secrets].filter((secret) => typeof secret === "string" && secret.length >= MIN_SECRET).flatMap(variants).sort((a, b) => b.length - a.length);
  /** @param {unknown} node @returns {any} */
  const walk = (node) => {
    if (typeof node === "string") return list.reduce((text, secret) => text.split(secret).join("<redacted>"), node);
    if (Array.isArray(node)) return node.map(walk);
    if (node && typeof node === "object") return Object.fromEntries(Object.entries(node).map(([key, item]) => [walk(key), walk(item)]));
    return node;
  };
  return walk(value);
}

module.exports = { CLOUD_BLOCKED, domainLock, cloudBlocked, redact, hostOf, normHost };
