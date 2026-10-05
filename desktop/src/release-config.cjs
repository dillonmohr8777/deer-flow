"use strict";

/** @param {NodeJS.ProcessEnv} environment */
function releaseSigning(environment) {
  const identity = environment.MOMOBOT_SIGNING_IDENTITY;
  const profile = environment.MOMOBOT_NOTARY_PROFILE;
  if (identity === undefined && profile === undefined) return { mode: "ad-hoc", identity: undefined, profile: undefined };
  if (!identity || !profile || identity !== identity.trim() || profile !== profile.trim() || !identity.startsWith("Developer ID Application: ") || /[\r\n\0]/u.test(identity + profile)) {
    throw new Error("Distribution requires a Developer ID Application identity and an existing notarytool Keychain profile together.");
  }
  return { mode: "developer-id", identity, profile };
}

/** @param {string} revision */
function validateSourceRevision(revision) {
  if (!/^[a-f0-9]{40}$/u.test(revision)) throw new Error("A full Git source revision is required.");
  return revision;
}

/** @param {{version:string, electron:string, revision:string, dirty:boolean, signing:string, builtAt:string, checksums:Record<string,string>}} input */
function publicReleaseMetadata(input) {
  return {
    schemaVersion: 1,
    product: "MomoBot",
    version: input.version,
    builtAt: input.builtAt,
    platform: "darwin-arm64",
    electron: input.electron,
    source: { revision: validateSourceRevision(input.revision), dirty: input.dirty },
    signing: input.signing,
    apiCredentialsBundled: false,
    artifacts: Object.entries(input.checksums).map(([filename, sha256]) => {
      if (!/^MomoBot-mac-arm64\.(?:zip|dmg)$/u.test(filename) || !/^[a-f0-9]{64}$/u.test(sha256)) throw new Error("Invalid release artifact checksum.");
      return { filename, sha256 };
    }),
  };
}

module.exports = { releaseSigning, validateSourceRevision, publicReleaseMetadata };
