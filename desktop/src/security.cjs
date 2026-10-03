"use strict";

const DEFAULT_ENDPOINT = "http://127.0.0.1:2030/workspace";
const MAX_ARTIFACT_BYTES = 20 * 1024 * 1024;
const EXECUTABLE_EXTENSIONS = /\.(?:app|exe|com|bat|cmd|msi|msp|ps1|sh|bash|zsh|fish|command|desktop|js|cjs|mjs|vbs|vbe|wsf|hta|py|pyw|rb|pl|jar|dll|so|dylib|wasm|scpt|applescript|lnk|url|webloc|pkg|dmg|deb|rpm)(?:\.|$)/i;

/** @param {string} hostname */
function isLoopbackHostname(hostname) {
  return hostname === "localhost" || hostname === "127.0.0.1" || hostname === "[::1]";
}

/** @param {unknown} value */
function validateEndpoint(value) {
  if (typeof value !== "string" || value.length > 2048 || [...value].some((char) => char.charCodeAt(0) < 32 || char.charCodeAt(0) === 127 || char === "\\")) {
    throw new Error("Enter a valid workspace URL.");
  }
  let url;
  try {
    url = new URL(value.trim());
  } catch {
    throw new Error("Enter a complete workspace URL, including https://.");
  }
  if (url.username || url.password || url.hash || url.search) {
    throw new Error("Use a workspace URL without passwords, query parameters, or fragments.");
  }
  if (url.protocol !== "https:" && !(url.protocol === "http:" && isLoopbackHostname(url.hostname))) {
    throw new Error("Remote workspaces require HTTPS. HTTP is allowed only on localhost.");
  }
  if (!url.hostname || url.hostname.endsWith(".")) {
    throw new Error("Enter a valid workspace hostname.");
  }
  if (url.pathname === "/") url.pathname = "/workspace";
  return url.toString();
}

/** @param {string} target @param {string} endpoint @param {string} settingsOrigin */
function isSameOriginNavigation(target, endpoint, settingsOrigin) {
  try {
    const parsed = new URL(target);
    if (parsed.username || parsed.password) return false;
    return parsed.origin === new URL(endpoint).origin || parsed.origin === settingsOrigin;
  } catch {
    return false;
  }
}

/** @param {unknown} value */
function safeExternalURL(value) {
  try {
    if (typeof value !== "string") return null;
    const url = new URL(value);
    if (url.protocol !== "https:" || url.username || url.password || isLoopbackHostname(url.hostname)) return null;
    return url.toString();
  } catch {
    return null;
  }
}

/**
 * @param {string} permission
 * @param {string} origin
 * @param {string} endpoint
 * @param {{mediaType?: string, mediaTypes?: readonly string[]}} details
 */
function permittedMediaRequest(permission, origin, endpoint, details = {}) {
  if (permission !== "media" || origin !== new URL(endpoint).origin) return false;
  if (details.mediaType) return details.mediaType === "audio";
  const types = details.mediaTypes;
  return Array.isArray(types) && types.length > 0 && types.every((type) => type === "audio");
}

function rendererPreferences() {
  return {
    nodeIntegration: false,
    nodeIntegrationInWorker: false,
    nodeIntegrationInSubFrames: false,
    contextIsolation: true,
    sandbox: true,
    webSecurity: true,
    allowRunningInsecureContent: false,
    webviewTag: false,
    navigateOnDragDrop: false,
    partition: "persist:momobot-openai-workspace",
  };
}

/** @param {unknown} value */
function artifactFilename(value) {
  if (typeof value !== "string" || !value || value.length > 160 || [...value].some((char) => char.charCodeAt(0) < 32 || char.charCodeAt(0) === 127 || char === "/" || char === "\\") || value.startsWith(".") || value.endsWith(".") || EXECUTABLE_EXTENSIONS.test(value)) return null;
  const filename = value.replace(/[^\w.-]/g, "-");
  return filename && filename !== "." && filename !== ".." ? filename : null;
}

/** @param {string} target @param {string} endpoint */
function isArtifactDownloadURL(target, endpoint) {
  try {
    const url = new URL(target);
    const origin = new URL(endpoint).origin;
    if (url.origin !== origin || url.username || url.password || url.search || url.hash) return false;
    if (url.protocol === "blob:") {
      const source = new URL(url.pathname);
      return !source.username && !source.password && !source.search && !source.hash && /^\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(source.pathname);
    }
    return (url.protocol === "https:" || url.protocol === "http:") && /^\/api\/openai-agents\/sessions\/[0-9a-f]{32}\/artifacts\/[A-Za-z0-9_-]{1,128}\/content$/.test(url.pathname);
  } catch {
    return false;
  }
}

/**
 * @param {{url:string,urlChain:string[],documentURL:string,frameURL:string,mimeType:string,filename:string,totalBytes:number,receivedBytes:number}} candidate
 * @param {string} endpoint
 */
function permittedArtifactDownload(candidate, endpoint) {
  try {
    const origin = new URL(endpoint).origin;
    if (new URL(candidate.documentURL).origin !== origin || new URL(candidate.frameURL).origin !== origin) return false;
    if (!isArtifactDownloadURL(candidate.url, endpoint) || !Array.isArray(candidate.urlChain) || !candidate.urlChain.length || !candidate.urlChain.every((url) => isArtifactDownloadURL(url, endpoint))) return false;
    const filename = artifactFilename(candidate.filename);
    const permittedMime = candidate.mimeType === "application/octet-stream" || (candidate.mimeType === "image/png" && filename?.toLowerCase().endsWith(".png")) || (candidate.mimeType === "application/json" && filename?.toLowerCase().endsWith(".json"));
    if (!permittedMime || !filename) return false;
    return [candidate.totalBytes, candidate.receivedBytes].every((bytes) => Number.isSafeInteger(bytes) && bytes >= 0 && bytes <= MAX_ARTIFACT_BYTES);
  } catch {
    return false;
  }
}

module.exports = { DEFAULT_ENDPOINT, MAX_ARTIFACT_BYTES, validateEndpoint, isSameOriginNavigation, safeExternalURL, permittedMediaRequest, rendererPreferences, artifactFilename, isArtifactDownloadURL, permittedArtifactDownload };
