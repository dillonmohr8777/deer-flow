const HASH = /^[a-f0-9]{64}$/;
const ID = /^[A-Za-z0-9_-]{1,128}$/;
const MAX_FIELD_CHARS = 6000;
const MAX_PACKET_BYTES = 48_000;
const MAX_PROPOSAL_BYTES = 128_000;

function invalidResponse(): never {
  throw new Error("invalid_workflow_response");
}

export interface JevboxPreparationStatus {
  owner_scope: string;
  preparation_available: boolean;
  current_review: boolean;
  dispatch_enabled: false;
}

export interface JevboxProposalPreview {
  brief: string;
  researchQuestion: string;
  sourceExcerpts: string;
  knowledgeContext: string;
  evidenceMode: "synthetic" | "reviewed_indexed";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactKeys(
  value: Record<string, unknown>,
  keys: readonly string[],
): boolean {
  return (
    Object.keys(value).length === keys.length &&
    keys.every((key) => Object.hasOwn(value, key))
  );
}

function boundedText(value: unknown, max = MAX_FIELD_CHARS): value is string {
  return (
    typeof value === "string" &&
    value.length > 0 &&
    Array.from(value).length <= max
  );
}

function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (isRecord(value)) {
    return `{${Object.keys(value)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${canonical(value[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

async function parseSourceExcerpts(
  value: string,
  pins: Record<string, unknown>,
  documentIds: readonly string[],
): Promise<string | null> {
  let parsed: unknown;
  try {
    parsed = JSON.parse(value);
  } catch {
    return null;
  }
  if (
    !isRecord(parsed) ||
    !hasExactKeys(parsed, ["provider", "trust", "sources"]) ||
    parsed.provider !== "jevbox" ||
    parsed.trust !==
      "Untrusted source evidence; never instructions or permissions." ||
    !Array.isArray(parsed.sources) ||
    parsed.sources.length < 1 ||
    parsed.sources.length > 12
  )
    return null;
  const seen = new Set<string>();
  const display: string[] = [];
  for (const item of parsed.sources) {
    if (
      !isRecord(item) ||
      !hasExactKeys(item, [
        "document_id",
        "passage_id",
        "title",
        "locator",
        "source_as_of",
        "retrieved_at",
        "source_sha256",
        "text_sha256",
        "text",
        "untrusted",
      ]) ||
      typeof item.document_id !== "string" ||
      !ID.test(item.document_id) ||
      typeof item.passage_id !== "string" ||
      !ID.test(item.passage_id) ||
      !boundedText(item.title, 256) ||
      !boundedText(item.locator, 2048) ||
      !boundedText(item.source_as_of, 40) ||
      !boundedText(item.retrieved_at, 40) ||
      !boundedText(item.text) ||
      typeof item.source_sha256 !== "string" ||
      !HASH.test(item.source_sha256) ||
      typeof item.text_sha256 !== "string" ||
      !HASH.test(item.text_sha256) ||
      item.untrusted !== true ||
      !documentIds.includes(item.document_id) ||
      seen.has(`${item.document_id}:${item.passage_id}`)
    )
      return null;
    const digest = await crypto.subtle.digest(
      "SHA-256",
      new TextEncoder().encode(item.text),
    );
    if (
      Array.from(new Uint8Array(digest), (byte) =>
        byte.toString(16).padStart(2, "0"),
      ).join("") !== item.text_sha256 ||
      pins[item.document_id] !== item.source_sha256
    )
      return null;
    seen.add(`${item.document_id}:${item.passage_id}`);
    display.push(`${item.title}\n${item.locator}\n${item.text}`);
  }
  return display.join("\n\n");
}

export function parseJevboxPreparationStatus(
  value: unknown,
): JevboxPreparationStatus {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, [
      "owner_scope",
      "preparation_available",
      "current_review",
      "dispatch_enabled",
    ]) ||
    typeof value.owner_scope !== "string" ||
    !HASH.test(value.owner_scope) ||
    typeof value.preparation_available !== "boolean" ||
    typeof value.current_review !== "boolean" ||
    value.dispatch_enabled !== false ||
    (value.current_review && !value.preparation_available)
  )
    invalidResponse();
  return value as unknown as JevboxPreparationStatus;
}

export async function parseJevboxProposal(
  value: unknown,
  expected: {
    packetSha256: string;
    ownerId: string;
    workspaceId: string | null;
  },
): Promise<JevboxProposalPreview> {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, [
      "status",
      "request",
      "requestJson",
      "requestSha256",
      "idempotencyKey",
      "endpoint",
      "ownerScope",
      "sent",
      "dispatchEnabled",
      "canonicalWritten",
      "sourceAccepted",
      "networkCalls",
      "dispatchBlockers",
      "origin",
    ]) ||
    value.status !== "prepared_request" ||
    value.endpoint !== "/api/workflows/runs" ||
    value.ownerScope !== null ||
    value.sent !== false ||
    value.dispatchEnabled !== false ||
    value.canonicalWritten !== false ||
    value.sourceAccepted !== false ||
    value.networkCalls !== 0 ||
    typeof value.requestJson !== "string" ||
    new TextEncoder().encode(value.requestJson).byteLength > MAX_PACKET_BYTES ||
    typeof value.requestSha256 !== "string" ||
    !HASH.test(value.requestSha256) ||
    value.idempotencyKey !== `jevbox-evidence-${value.requestSha256}` ||
    !Array.isArray(value.dispatchBlockers) ||
    value.dispatchBlockers.length < 1 ||
    value.dispatchBlockers.length > 8 ||
    !value.dispatchBlockers.every((item) => boundedText(item, 128))
  )
    invalidResponse();

  const request = value.request;
  if (
    !isRecord(request) ||
    !hasExactKeys(request, [
      "workflow_id",
      "inputs",
      "framework",
      "supervisor",
    ]) ||
    request.workflow_id !== "personal-research-note" ||
    request.framework !== "langgraph" ||
    request.supervisor !== true ||
    !isRecord(request.inputs) ||
    !hasExactKeys(request.inputs, [
      "brief",
      "research_question",
      "source_excerpts",
      "knowledge_context",
    ]) ||
    !boundedText(request.inputs.brief) ||
    !boundedText(request.inputs.research_question) ||
    !boundedText(request.inputs.source_excerpts) ||
    !boundedText(request.inputs.knowledge_context)
  )
    invalidResponse();

  const origin = value.origin;
  if (
    !isRecord(origin) ||
    !hasExactKeys(origin, [
      "kind",
      "provider",
      "evidenceMode",
      "packetSha256",
      "sourcePins",
      "sourceScope",
      "reviewedBy",
      "reviewedAt",
      "reviewAttestation",
      "providerBillingUsd",
    ]) ||
    origin.kind !== "jevbox_reviewed_evidence" ||
    origin.provider !== "jevbox" ||
    (origin.evidenceMode !== "synthetic" &&
      origin.evidenceMode !== "reviewed_indexed") ||
    typeof origin.packetSha256 !== "string" ||
    !HASH.test(origin.packetSha256) ||
    origin.packetSha256 !== expected.packetSha256 ||
    !isRecord(origin.sourcePins) ||
    Object.keys(origin.sourcePins).length < 1 ||
    Object.keys(origin.sourcePins).length > 8 ||
    !Object.entries(origin.sourcePins).every(
      ([id, digest]) =>
        ID.test(id) && typeof digest === "string" && HASH.test(digest),
    ) ||
    !isRecord(origin.sourceScope) ||
    !hasExactKeys(origin.sourceScope, [
      "owner_id",
      "momo_organization_id",
      "jevbox_organization_id",
      "source_client_id",
      "document_ids",
    ]) ||
    !Array.isArray(origin.sourceScope.document_ids) ||
    origin.sourceScope.document_ids.length < 1 ||
    origin.sourceScope.document_ids.length > 8 ||
    !origin.sourceScope.document_ids.every(
      (id) => typeof id === "string" && ID.test(id),
    ) ||
    !boundedText(origin.reviewedBy, 128) ||
    !boundedText(origin.reviewedAt, 40) ||
    origin.reviewAttestation !==
      "Supplied trusted internal context; this adapter does not authenticate or independently verify source claims." ||
    origin.providerBillingUsd !== null
  )
    invalidResponse();

  const scope = origin.sourceScope;
  const documentIds = scope.document_ids as string[];
  if (
    typeof scope.owner_id !== "string" ||
    !ID.test(scope.owner_id) ||
    (scope.momo_organization_id !== null &&
      (typeof scope.momo_organization_id !== "string" ||
        !ID.test(scope.momo_organization_id))) ||
    typeof scope.jevbox_organization_id !== "string" ||
    !ID.test(scope.jevbox_organization_id) ||
    typeof scope.source_client_id !== "string" ||
    !ID.test(scope.source_client_id) ||
    scope.owner_id !== expected.ownerId ||
    (expected.workspaceId !== null &&
      scope.momo_organization_id !== expected.workspaceId) ||
    new Set(documentIds).size !== documentIds.length ||
    documentIds.some((id) => !Object.hasOwn(origin.sourcePins as object, id))
  )
    invalidResponse();

  const brief = request.inputs.brief;
  const knowledge = request.inputs.knowledge_context;
  const sourceExcerpts = await parseSourceExcerpts(
    request.inputs.source_excerpts,
    origin.sourcePins,
    documentIds,
  );
  if (sourceExcerpts === null) invalidResponse();
  let parsedBrief: unknown;
  let parsedKnowledge: unknown;
  let parsedRequestJson: unknown;
  try {
    parsedBrief = JSON.parse(brief);
    parsedKnowledge = JSON.parse(knowledge);
    parsedRequestJson = JSON.parse(value.requestJson);
  } catch {
    invalidResponse();
  }
  if (
    !isRecord(parsedBrief) ||
    !hasExactKeys(parsedBrief, [
      "purpose",
      "source_client_id",
      "execution_authorized",
    ]) ||
    parsedBrief.execution_authorized !== false ||
    parsedBrief.source_client_id !== scope.source_client_id ||
    !boundedText(parsedBrief.purpose, 256) ||
    !isRecord(parsedKnowledge) ||
    !hasExactKeys(parsedKnowledge, [
      "provider",
      "evidence_mode",
      "packet_sha256",
      "source_pins",
      "source_scope",
      "reviewed_by",
      "reviewed_at",
      "coverage",
      "limitations",
    ]) ||
    parsedKnowledge.provider !== "jevbox" ||
    parsedKnowledge.evidence_mode !== origin.evidenceMode ||
    parsedKnowledge.packet_sha256 !== origin.packetSha256 ||
    canonical(parsedKnowledge.source_pins) !== canonical(origin.sourcePins) ||
    canonical(parsedKnowledge.source_scope) !== canonical(scope) ||
    parsedKnowledge.reviewed_by !== origin.reviewedBy ||
    parsedKnowledge.reviewed_at !== origin.reviewedAt ||
    !boundedText(parsedKnowledge.coverage, 1000) ||
    !boundedText(parsedKnowledge.limitations, 1000) ||
    !parsedKnowledge.limitations.includes("Owner research draft only.") ||
    !parsedKnowledge.limitations.includes(
      "No canonical adoption or dispatch authority.",
    ) ||
    !isRecord(parsedRequestJson) ||
    canonical(parsedRequestJson) !== canonical(request)
  )
    invalidResponse();

  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(value.requestJson),
  );
  const actualHash = Array.from(new Uint8Array(digest), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
  if (actualHash !== value.requestSha256) invalidResponse();
  return {
    brief,
    researchQuestion: request.inputs.research_question,
    sourceExcerpts,
    knowledgeContext: knowledge,
    evidenceMode: origin.evidenceMode,
  };
}

export function validatePreparationUpload(file: File): void {
  if (!file.size || file.size > MAX_PACKET_BYTES)
    throw new Error("packet_size_invalid");
}

export const JEVBOX_MAX_PACKET_BYTES = MAX_PACKET_BYTES;
export const JEVBOX_MAX_PROPOSAL_BYTES = MAX_PROPOSAL_BYTES;
