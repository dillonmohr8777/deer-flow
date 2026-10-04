"use strict";

const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const crypto = require("node:crypto");
const { execFileSync } = require("node:child_process");
const { packager } = require("@electron/packager");
const manifest = require("../package.json");
const { releaseSigning, validateSourceRevision, publicReleaseMetadata } = require("../src/release-config.cjs");

const root = path.resolve(__dirname, "..");

/** @param {string} command @param {string[]} args */
function run(command, args) {
  return execFileSync(command, args, { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }).trim();
}

async function main() {
  if (process.platform !== "darwin" || process.arch !== "arm64") throw new Error("This build targets Apple Silicon macOS.");
  const signing = releaseSigning(process.env);
  const revision = validateSourceRevision(run("git", ["-C", root, "rev-parse", "HEAD"]));
  const dirty = Boolean(run("git", ["-C", root, "status", "--porcelain", "--", "."]));
  if (signing.mode === "developer-id" && dirty) throw new Error("Developer ID releases require committed desktop and icon sources.");
  if (signing.identity) {
    const identities = run("security", ["find-identity", "-v", "-p", "codesigning"]);
    if (!identities.includes(`"${signing.identity}"`)) throw new Error("Configured Developer ID signing identity is unavailable.");
  }
  const releaseRoot = process.env.MOMOBOT_RELEASE_DIR || path.join(os.homedir(), "Documents/Codex/momobot-openai-app-release");
  const stamp = new Date().toISOString().replace(/[:.]/gu, "-");
  const destination = path.join(releaseRoot, `build-${stamp}`);
  const iconset = path.join(root, ".build/MomoBot.iconset");
  const iconSource = path.join(root, "branding/momobot-design-c-v1.png");
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
    appVersion: manifest.version,
    platform: "darwin",
    arch: "arm64",
    electronVersion: manifest.devDependencies.electron,
    ...(signing.identity ? { osxSign: { identity: signing.identity, continueOnError: false, optionsForFile: () => ({ hardenedRuntime: true }) } } : {}),
    out: destination,
    icon,
    asar: true,
    prune: true,
    overwrite: false,
    ignore: (candidate) => Boolean(candidate) && !/^\/(?:src|ui|assets|node_modules)(?:\/|$)/u.test(candidate) && !/^\/(?:package\.json|LICENSE)$/u.test(candidate),
    extendInfo: {
      NSMicrophoneUsageDescription: "MomoBot uses your microphone only when you start voice input in your workspace.",
    },
  });
  const appPath = path.join(bundleDirectory, "MomoBot.app");
  if (signing.mode === "ad-hoc") run("codesign", ["--force", "--deep", "--sign", "-", appPath]);
  run("codesign", ["--verify", "--deep", "--strict", appPath]);
  const zipPath = path.join(destination, "MomoBot-mac-arm64.zip");
  const dmgPath = path.join(destination, "MomoBot-mac-arm64.dmg");
  run("ditto", ["-c", "-k", "--sequesterRsrc", "--keepParent", appPath, zipPath]);
  run("hdiutil", ["create", "-volname", "MomoBot", "-srcfolder", bundleDirectory, "-format", "UDZO", dmgPath]);
  if (signing.profile) {
    // Existing Keychain profile only; no password, API key, or certificate is exported.
    const appResult = JSON.parse(run("xcrun", ["notarytool", "submit", zipPath, "--keychain-profile", signing.profile, "--wait", "--output-format", "json"]));
    if (appResult.status !== "Accepted") throw new Error("Application notarization was not accepted.");
    run("xcrun", ["stapler", "staple", appPath]);
    run("xcrun", ["stapler", "validate", appPath]);
    // Replace only artifacts created in this new build directory with stapled contents.
    await fs.unlink(zipPath);
    await fs.unlink(dmgPath);
    run("ditto", ["-c", "-k", "--sequesterRsrc", "--keepParent", appPath, zipPath]);
    run("hdiutil", ["create", "-volname", "MomoBot", "-srcfolder", bundleDirectory, "-format", "UDZO", dmgPath]);
    run("codesign", ["--sign", signing.identity || "", "--timestamp", dmgPath]);
    const dmgResult = JSON.parse(run("xcrun", ["notarytool", "submit", dmgPath, "--keychain-profile", signing.profile, "--wait", "--output-format", "json"]));
    if (dmgResult.status !== "Accepted") throw new Error("Disk image notarization was not accepted.");
    run("xcrun", ["stapler", "staple", dmgPath]);
    run("xcrun", ["stapler", "validate", dmgPath]);
    run("spctl", ["--assess", "--type", "execute", appPath]);
  }
  /** @type {Record<string,string>} */
  const checksums = {};
  for (const file of [zipPath, dmgPath]) checksums[path.basename(file)] = crypto.createHash("sha256").update(await fs.readFile(file)).digest("hex");
  const artifact = publicReleaseMetadata({
    version: manifest.version,
    builtAt: new Date().toISOString(),
    electron: manifest.devDependencies.electron,
    revision,
    dirty,
    signing: signing.mode === "developer-id" ? "Developer ID signed; Apple notarized; app and DMG tickets stapled and validated" : "ad-hoc local signature; not notarized",
    checksums,
  });
  await fs.writeFile(path.join(destination, "release.json"), `${JSON.stringify(artifact, null, 2)}\n`);
  await fs.writeFile(path.join(destination, "build-paths.json"), `${JSON.stringify({ appPath, zipPath, dmgPath }, null, 2)}\n`, { mode: 0o600 });
  await fs.writeFile(path.join(destination, "SHA256SUMS"), Object.entries(checksums).map(([filename, digest]) => `${digest}  ${filename}\n`).join(""));
  process.stdout.write(`${JSON.stringify(artifact, null, 2)}\n`);
}

main().catch((error) => {
  process.stderr.write(`Desktop package failed: ${error.message}\n`);
  process.exitCode = 1;
});
