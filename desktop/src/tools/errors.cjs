"use strict";

/** @typedef {"DOMAIN_MISMATCH"|"DOMAIN_LOCK_DENIED"|"CLOUD_UNAVAILABLE"|"PROTECTED_SITE"} PolicyCode */
class PolicyError extends Error {
  /** @param {PolicyCode} code @param {string} message */
  constructor(code, message) { super(message); this.code = code; }
}
/** Only policy-created errors carry policy evidence; arbitrary error strings cannot impersonate it.
 * @param {unknown} error @returns {PolicyCode|"TOOL_ERROR"}
 */
function errorCategory(error) { return error instanceof PolicyError ? error.code : "TOOL_ERROR"; }
module.exports = { PolicyError, errorCategory };
