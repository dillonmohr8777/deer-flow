"use strict";

const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const crypto = require("node:crypto");
const { execFileSync } = require("node:child_process");
const { packager } = require("@electron/packager");

const root = path.resolve(__dirname, "..");

/** @param {string} command @param {string[]} args */
function run(command, args) {
  return execFileSync(command, args, { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }).trim();
}

async function main() {
  if (process.platform !== "darwin" || process.arch !== "arm64") throw new Error("This build targets Apple Silicon macOS.");
  const releaseRoot = process.env.MOMOBOT_RELEASE_DIR || path.join(os.homedir(), "Documents/Codex/momobot-openai-app-release");
  const stamp = new Date().toISOString().replace(/[:.]/gu, "-");
  const destination = path.join(releaseRoot, `build-${stamp}`);
  const iconset = path.join(root, ".build/MomoBot.iconset");
  const iconSource = path.resolve(root, "../frontend/public/icons/icon-512.png");
  const assets = path.join(root, "assets");
  await fs.mkdir(iconset, { recursive: true });
  await fs.mkdir(assets, { recursive: true });
  await fs.copyFile(iconSource, path.join(assets, "icon.png"));
  for (const size of [16, 32, 128, 256, 512]) {
    for (const scale of [1, 2]) {
      const filename = `icon_${size}x${size}${scale === 2 ? "@2x" : ""}.png`;
      run("sips", ["-z", String(size * scale), String(size * scale), iconSource, "--out", path.join(iconset, filename)]);
    }
  }
  const icon = path.join(assets, "MomoBot.icns");
  run("iconutil", ["-c", "icns", iconset, "-o", icon]);
  const [bundleDirectory] = await packager({
    dir: root,
    name: "MomoBot",
    appBundleId: "com.momentum.momobot.openai",
    appVersion: "0.1.0",
    platform: "darwin",
    arch: "arm64",
    electronVersion: require("../package.json").devDependencies.electron,
    out: destination,
    icon,
    asar: true,
    prune: true,
    overwrite: false,
    ignore: [/^\/\.build(?:\/|$)/u, /^\/tests(?:\/|$)/u, /^\/scripts(?:\/|$)/u, /^\/out(?:\/|$)/u, /^\/README\.md$/u, /^\/package-lock\.json$/u],
    extendInfo: {
      NSMicrophoneUsageDescription: "MomoBot uses your microphone only when you start voice input in your workspace.",
    },
  });
  const appPath = path.join(bundleDirectory, "MomoBot.app");
  // An ad-hoc signature validates this local build's integrity; it is not a
  // Developer ID signature and does not certify it for external distribution.
  run("codesign", ["--force", "--deep", "--sign", "-", appPath]);
  run("codesign", ["--verify", "--deep", "--strict", appPath]);
  const zipPath = path.join(destination, "MomoBot-mac-arm64.zip");
  const dmgPath = path.join(destination, "MomoBot-mac-arm64.dmg");
  run("ditto", ["-c", "-k", "--sequesterRsrc", "--keepParent", appPath, zipPath]);
  run("hdiutil", ["create", "-volname", "MomoBot", "-srcfolder", bundleDirectory, "-format", "UDZO", dmgPath]);
  /** @type {Record<string,string>} */
  const checksums = {};
  const artifact = {
    builtAt: new Date().toISOString(),
    appPath,
    zipPath,
    dmgPath,
    platform: "darwin-arm64",
    electron: require("../package.json").devDependencies.electron,
    signing: "ad-hoc local signature; no Developer ID identity; not notarized",
    apiCredentialsBundled: false,
    sha256: checksums,
  };
  for (const file of [zipPath, dmgPath]) artifact.sha256[path.basename(file)] = crypto.createHash("sha256").update(await fs.readFile(file)).digest("hex");
  await fs.writeFile(path.join(destination, "release.json"), `${JSON.stringify(artifact, null, 2)}\n`);
  process.stdout.write(`${JSON.stringify(artifact, null, 2)}\n`);
}

main().catch((error) => {
  process.stderr.write(`Desktop package failed: ${error.message}\n`);
  process.exitCode = 1;
});
