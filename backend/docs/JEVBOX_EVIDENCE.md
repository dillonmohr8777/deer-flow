# Reviewed Jevbox evidence preparation

`app/gateway/jevbox_evidence.py` prepares an **unsent** `personal-research-note`
request from exact reviewed evidence bytes. It has no route, MCP transport,
provider call, filesystem/ledger writer, scheduler or native dispatch hook.
The existing workflow still owns execution and its admission, uncertain holds,
independent review and artifact receipts. Native installation and useful output
are unverified by this source adapter.

## Internal API and trust boundary

```python
prepare_jevbox_evidence(
    packet_bytes,
    admission=trusted_internal_preparation_context,
    now=aware_current_datetime,
)
```

`TrustedJevboxPreparationContext` is an explicit internal argument, not a web
request model. Never construct it from packet JSON, request fields, model text,
checkpoint metadata or a claimed owner header. Existing trusted admission must
verify the active original owner, current organization membership, storage
principal, exact selected document scope and current review/source pins first.
Creating this dataclass manually does not prove authenticated admission.
The adapter checks consistency only; it does not perform authentication.

Its required fields are:

- `actor_user_id`, `owner_user_id`, `storage_user_id`: the admitted identities;
  all three must be the same original owner.
- `momo_organization_id`: exact admitted Momo organization ID or `None` for the
  existing personal scope; never invent an organization or fall back to another.
- `jevbox_organization_id`, `source_client_id`: explicit nonempty admitted evidence
  scope; a client ID does not grant client execution authority.
- `document_ids`: an immutable tuple of 1–8 unique indexed document IDs.
- `source_pins`: an immutable tuple of `(document_id, source_sha256)` pairs,
  covering that exact document scope. Pins belong to the reviewed imported
  original source bytes, independently supplied by the caller.
- `expected_packet_sha256`, `expected_reviewed_by`, `expected_reviewed_at`:
  caller-supplied current review pins; the first hashes exact UTF-8 packet bytes.
- `review_expires_at`: explicit caller-selected review expiry; the reviewed
  timestamp, current clock and expiry must be aware and correctly ordered.
- `owner_scope_active`: must be the actual boolean `True`, supplied internally.

IDs use 1–128 ASCII letters, digits, underscores or hyphens. Review timestamps
are aware `datetime` objects in this internal context. All errors use fixed
codes without echoing source text, credentials or identity values.

## Closed packet version one

The following object fields are required; additional fields at every object
level are rejected. Packet JSON cannot supply the trusted context.

```text
schema_version: 1 (integer, not boolean)
kind: "jevbox_reviewed_evidence"
provider: "jevbox"
purpose: "owner_research_draft"
evidence_mode: "synthetic" | "reviewed_indexed"
scope:
  owner_id: admitted owner ID
  momo_organization_id: exact admitted Momo organization ID | null (personal scope)
  jevbox_organization_id: admitted Jevbox organization ID
  source_client_id: admitted evidence client ID
  document_ids: exact admitted ordered document ID list
reviewed_at: ISO timestamp with explicit timezone
reviewed_by: admitted reviewer ID
research_question: nonempty text, maximum 6000 characters
coverage: nonempty description of selected/missing evidence, maximum 1000 characters
sources: list of 1–12 complete source records
  document_id: admitted indexed document ID
  passage_id: actual selected passage ID
  title: nonempty text, maximum 256 characters
  locator: opaque "jevbox:<document_id>:<passage_id>" or public HTTPS source reference
  source_as_of: ISO timestamp with explicit timezone
  retrieved_at: ISO timestamp with explicit timezone
  source_sha256: caller-pinned original imported source hash
  text_sha256: SHA256 of exact UTF-8 excerpt text bytes
  text: nonempty complete selected excerpt, maximum 6000 characters
  untrusted: true (boolean)
```

Duplicate JSON keys, malformed/nonfinite/deep JSON, invalid UTF-8 text,
credential-shaped content, empty selections, duplicate passages, wrong scope,
changed pins and stale/future reviews fail closed. Source as-of must precede
retrieval, and retrieval must precede review. Locators are references only,
with a maximum of 2048 characters; no resolver, network fetch or renderer handler
runs. The opaque provider reference must match the record's document and passage
IDs exactly. Jevbox search exposes actual fetch IDs as `documentId:passageId`;
the `jevbox:` prefix labels provenance and is not a fabricated network endpoint.
Current native passage IDs such as `node-1-passage-2` fit the bounded ID contract.
Private documents can use this opaque reference because Jevbox's library UI URL
may be loopback HTTP and its original source may have no public URL. Never
rewrite that UI URL as a claimed public origin. Public HTTPS origin references
refuse userinfo, control/whitespace, nonstandard ports and literal private/local
addresses; DNS and provider authenticity remain unverified by this pure adapter.

The raw packet is at most 48,000 bytes. The existing native workflow limits each
input field to 6000 characters and its total JSON input to 48,000 bytes. Full
records must fit together; the adapter rejects an oversized selection and never
truncates an excerpt, drops a source or changes text under its hash. Request
encoding is deterministic. Equivalent repeated preparation retains the body
hash and `jevbox-evidence-<requestSha256>` idempotency key.

## Proposal and deferred execution

The result retains the established `prepared_request` envelope: `request`,
`requestJson`, `requestSha256`, `idempotencyKey`, endpoint `/api/workflows/runs`,
`sent:false` and `ownerScope:null`. It additionally fixes `dispatchEnabled`,
`canonicalWritten` and `sourceAccepted` to false, records zero network calls,
keeps actual provider billing unknown, and lists the remaining dispatch gates.

The request is `framework:langgraph`, `supervisor:true` and workflow
`personal-research-note`, with the existing `brief`, `research_question`,
`source_excerpts`, `knowledge_context` inputs validated against the real catalog.
All source text remains untrusted evidence, including source-instruction
attacks. Unknown dates, disagreements and incomplete coverage remain visible.
The output identifies Jevbox; it neither impersonates original PR447/X evidence
nor manufactures RAGFlow/native `knowledge_sources` citation artifacts.
There is no automatic native Sources-panel integration.

Tests use clearly synthetic owner/org/document/passage IDs and source text only.
The fixture in `tests/test_jevbox_evidence.py` is executable contract evidence,
not an account, import, retrieved passage or accepted business result. Public
source staging with no actual Jevbox document IDs cannot be promoted into an
indexed packet by inventing IDs.

Actual search/fetch/recovery hookup, provider source readback, server-side tool
allowlisting, shared USD20/calendar-month accounting and native dispatch remain
disabled. The monthly period is UTC in the prepared external prototype profile;
this adapter provides no accounting or additional spend allowance. Retain all
existing uncertain reservations and stricter inherited ceilings, including the
native USD0.264 hold and original PR447 X USD16 cumulative history. No hold or
ledger may be reset to create prototype capacity.

Offline checks: run `make test`, `make test-blocking-io`, scoped Pyright and
Ruff/format in `backend/`. Native acceptance additionally needs installed
source, normal original-owner app authentication, verified scoped Jevbox source
readback, one independently reviewed useful workflow artifact and its matching
saved byte-count/SHA256 receipt.
