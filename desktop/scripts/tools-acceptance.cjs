"use strict";

/** Source-harness criteria only; this never certifies a packaged application.
 * @param {Record<string, any>} proof @returns {string[]}
 */
function acceptanceFailures(proof) {
  const checks = {
    backendAvailable: proof.backendAvailable === true,
    fetch: proof.fetch?.ok === true,
    domainLock: proof.domainLockLive?.refused === true && proof.domainLockLive?.category === "DOMAIN_MISMATCH",
    login: proof.login?.status === "submitted" && proof.afterLogin?.authenticatedDashboard === true && proof.afterLogin?.stillOnLoginForm === false,
    screenshots: proof.screenshots?.before === true && proof.screenshots?.after === true,
    release: proof.release?.primary === true && proof.release?.other === true,
    ledger: proof.ledger?.keysOnly === true && proof.ledger?.hasLogin === true && proof.ledger?.rows > 0,
    outputScan: proof.leakScan?.forbiddenForms > 0 && Array.isArray(proof.leakScan?.hits) && proof.leakScan.hits.length === 0,
  };
  return Object.entries(checks).filter(([, ok]) => !ok).map(([name]) => name);
}
module.exports = { acceptanceFailures };
