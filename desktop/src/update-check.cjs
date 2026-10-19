"use strict";

/** @param {unknown} version */
function parseVersion(version) {
  const match = typeof version === "string" ? /^(\d{1,6})\.(\d{1,6})\.(\d{1,6})$/u.exec(version) : null;
  if (!match) throw new Error("Invalid version.");
  return match.slice(1).map(Number);
}

/** Positive when `a` is newer than `b`. @param {string} a @param {string} b */
function compareVersions(a, b) {
  const left = parseVersion(a);
  const right = parseVersion(b);
  for (let index = 0; index < 3; index++) if (left[index] !== right[index]) return left[index] - right[index];
  return 0;
}

/** The release folder URL the installer downloaded from; HTTPS only, no credentials, query or fragment. @param {unknown} value */
function validateUpdateURL(value) {
  if (typeof value !== "string" || !value) return undefined;
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" || url.username || url.password || url.search || url.hash) return undefined;
    if (!url.pathname.endsWith("/")) url.pathname += "/";
    // The URL is shown inside a Terminal command, so allow only characters with no shell meaning.
    return /^https:\/\/[A-Za-z0-9.-]+(?::\d+)?\/[A-Za-z0-9._~/%-]*$/u.test(url.toString()) ? url.toString() : undefined;
  } catch {
    return undefined;
  }
}

/**
 * Reads `<updateURL>release.json` (written by package:mac) and compares it with the running version.
 * @param {{updateURL:string, currentVersion:string, fetchImpl?:(url:string, init:object)=>Promise<{ok:boolean,json:()=>Promise<any>}>}} options
 * @returns {Promise<{status:"newer"|"current", latest:string}|{status:"unreachable"}>}
 */
async function checkForUpdate({ updateURL, currentVersion, fetchImpl = fetch }) {
  try {
    const response = await fetchImpl(new URL("release.json", updateURL).toString(), { signal: AbortSignal.timeout(10_000) });
    if (!response.ok) return { status: "unreachable" };
    const manifest = await response.json();
    if (manifest?.product !== "MomoBot") return { status: "unreachable" };
    return { status: compareVersions(manifest.version, currentVersion) > 0 ? "newer" : "current", latest: manifest.version };
  } catch {
    return { status: "unreachable" };
  }
}

module.exports = { compareVersions, validateUpdateURL, checkForUpdate };
