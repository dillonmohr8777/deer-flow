# Jevbox preparation-only route

`POST /api/workflows/jevbox/prepare` is an opt-in, authenticated preparation route. It applies the existing `runs:read` permission, CSRF middleware, expected workflow-scope header, and active server-resolved actor/organization/storage identity. It returns the existing adapter's unsent proposal. It does not initialize or call `WorkflowService`, create a run, invoke a provider, retrieve data, write a ledger, or dispatch work. Existing run creation and resume authorization, entitlement, and budget gates are unchanged.

The route returns `404 preparation_unavailable` unless the gateway starts with `MOMOBOT_JEVBOX_PREPARATION_FILE` set to a valid binding file. An explicitly set but empty, malformed, oversized, symlinked, non-regular, non-owner-owned, or group/world-writable file fails startup with a fixed error. The file is loaded once at startup with a 64,000-byte cap. Keep it in a private owner-only location; it contains reviewer and source scope metadata, not credentials. Do not check in a real binding.

The binding must belong to the Gateway process's effective operating-system UID, with no group or world write bit. Verify the actual runtime UID before selecting a mounted file; a file owned by the desktop user can fail this check in a root container. Keep that check intact during setup. Loading a binding does not prove an authenticated Jevbox import or retrieval.

The file is strict UTF-8 JSON with exactly the following structure and no duplicate keys:

```json
{
  "schema_version": 1,
  "context": {
    "actor_user_id": "synthetic-owner",
    "owner_user_id": "synthetic-owner",
    "storage_user_id": "synthetic-owner",
    "momo_organization_id": "synthetic-momo-org",
    "jevbox_organization_id": "synthetic-jevbox-org",
    "source_client_id": "synthetic-client",
    "document_ids": ["synthetic-document"],
    "source_pins": [{"document_id": "synthetic-document", "sha256": "<64 lowercase hex characters>"}],
    "expected_packet_sha256": "<64 lowercase hex characters>",
    "expected_reviewed_by": "synthetic-reviewer",
    "expected_reviewed_at": "2026-10-04T12:00:00+00:00",
    "review_expires_at": "2026-10-04T13:00:00+00:00",
    "owner_scope_active": true
  }
}
```

Send the exact reviewed packet bytes as `application/json`; request bytes are capped at 48,000 and the adapter checks the complete packet hash, review identity/time, scope, document set, and source hashes against the startup binding. Request fields cannot set or replace trusted context. A review that expires after startup is rejected on the next request. No response enables dispatch or sets owner scope.
