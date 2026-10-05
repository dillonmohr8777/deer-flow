"use strict";

const clean = (/** @type {string} */ v) => v === v.trim() && !/[\r\n\0]/u.test(v);

/**
 * Notarization credentials come from the environment only, never the repo.
 * Preferred: App Store Connect API key (APPLE_API_KEY = path to .p8, APPLE_API_KEY_ID, APPLE_API_ISSUER).
 * Alternative: an existing notarytool Keychain profile (MOMOBOT_NOTARY_PROFILE).
 * @param {NodeJS.ProcessEnv} environment
 */
function releaseSigning(environment) {
  const identity = environment.MOMOBOT_SIGNING_IDENTITY;
  const profile = environment.MOMOBOT_NOTARY_PROFILE;
  const { APPLE_API_KEY: keyPath, APPLE_API_KEY_ID: keyId, APPLE_API_ISSUER: issuer } = environment;
  const apiVars = [keyPath, keyId, issuer];
  const apiCount = apiVars.filter((v) => v !== undefined).length;
  if (identity === undefined && profile === undefined && apiCount === 0) return { mode: "ad-hoc", identity: undefined, profile: undefined, apiKey: undefined };
  const fail = () => new Error("Distribution requires a Developer ID Application identity plus either a notarytool Keychain profile or APPLE_API_KEY, APPLE_API_KEY_ID and APPLE_API_ISSUER.");
  if (!identity || !identity.startsWith("Developer ID Application: ") || !clean(identity)) throw fail();
  if (apiCount > 0 && profile !== undefined) throw fail();
  if (apiCount > 0) {
    if (apiCount !== 3 || apiVars.some((v) => !v || !clean(/** @type {string} */ (v))) || !/^\/.+\.p8$/u.test(/** @type {string} */ (keyPath))) throw fail();
    return { mode: "developer-id", identity, profile: undefined, apiKey: { path: /** @type {string} */ (keyPath), id: /** @type {string} */ (keyId), issuer: /** @type {string} */ (issuer) } };
  }
  if (!profile || !clean(profile)) throw fail();
  return { mode: "developer-id", identity, profile, apiKey: undefined };
}

/** notarytool credential arguments for either auth route. @param {ReturnType<typeof releaseSigning>} signing */
function notaryAuthArgs(signing) {
  if (signing.apiKey) return ["--key", signing.apiKey.path, "--key-id", signing.apiKey.id, "--issuer", signing.apiKey.issuer];
  if (signing.profile) return ["--keychain-profile", signing.profile];
  throw new Error("No notarization credentials configured.");
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

module.exports = { releaseSigning, notaryAuthArgs, validateSourceRevision, publicReleaseMetadata };
