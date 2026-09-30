"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { randomUUID } = require("node:crypto");
const { MAX_ARTIFACT_BYTES, artifactFilename, permittedArtifactDownload } = require("./security.cjs");

/**
 * @param {Electron.Event} event
 * @param {Electron.DownloadItem} item
 * @param {{endpoint:string,documentURL:string,frameURL:string,ownedFrame:boolean,downloadsDirectory:string,confirm:(filename:string)=>boolean,onResult?:(result:{saved:boolean,path?:string})=>void}} options
 */
function handleArtifactDownload(event, item, options) {
  const candidate = {
    url: item.getURL(), urlChain: item.getURLChain(), documentURL: options.documentURL,
    frameURL: options.frameURL, mimeType: item.getMimeType(), filename: item.getFilename(),
    totalBytes: item.getTotalBytes(), receivedBytes: item.getReceivedBytes(),
  };
  if (!options.ownedFrame || !permittedArtifactDownload(candidate, options.endpoint)) {
    event.preventDefault();
    return false;
  }
  const filename = artifactFilename(candidate.filename);
  if (!filename || (!item.hasUserGesture() && !options.confirm(filename))) {
    event.preventDefault();
    return false;
  }
  let destination;
  let reserved = false;
  try {
    if (!path.isAbsolute(options.downloadsDirectory)) throw new Error("Invalid download location");
    fs.mkdirSync(options.downloadsDirectory, { recursive: true });
    // Reserve a private unique file; never overwrite a user-owned existing file.
    destination = path.join(options.downloadsDirectory, `MomoBot-${randomUUID()}-${filename}`);
    const fd = fs.openSync(destination, "wx", 0o600);
    reserved = true;
    fs.closeSync(fd);
    item.setSavePath(destination);
  } catch {
    if (reserved && destination) fs.rmSync(destination, { force: true });
    event.preventDefault();
    return false;
  }
  const savedPath = destination;
  let overLimit = false;
  item.on("updated", () => {
    if (item.getReceivedBytes() > MAX_ARTIFACT_BYTES || item.getTotalBytes() > MAX_ARTIFACT_BYTES) {
      overLimit = true;
      item.cancel();
    }
  });
  item.once("done", (_event, state) => {
    let saved = false;
    try {
      const info = fs.lstatSync(savedPath);
      saved = state === "completed" && !overLimit && item.getReceivedBytes() <= MAX_ARTIFACT_BYTES && info.isFile() && !info.isSymbolicLink() && info.size <= MAX_ARTIFACT_BYTES;
      if (saved) fs.chmodSync(savedPath, 0o600);
    } catch { /* Incomplete/missing files are never reported as saved. */ }
    if (!saved) fs.rmSync(savedPath, { force: true });
    options.onResult?.(saved ? { saved: true, path: savedPath } : { saved: false });
    // Saving never launches a file, Finder or an external application.
  });
  return true;
}

module.exports = { handleArtifactDownload };
