# Progress

Ready for review: the installable extension, durable store, authenticated dashboard, and synthetic acceptance suite are complete in an isolated branch based on current origin/main. The earlier prototype remains untouched.

Decisions: use the supported MomoBot extension mechanism, not another platform. No current VHIN CRM identity established by records. Local CLI Composio HubSpot search returned no connected HubSpot toolkit; this does not prove no external CRM exists. Implement a persistent placement case store inside the existing MomoBot boundary with adapter contracts for Grace's form and the account providers. No client sends or real billing.

Verified: 22 synthetic HTTP/security/restart tests pass; Ruff lint and format pass. A 390 px rendered dashboard has no horizontal overflow, uses 16 px body text, and has no hit target below 44 px. The independent Claude API review completed; all material mobile-shell findings were fixed and retested.

Production activation remains separate and fail-closed: the live extension list has no VHIN installation, and no production VHIN organization binding is established. Activation requires Justin's existing MomoBot membership, Grace's membership if she will use the desk, exact host-stamped IDs, a private persistent volume plus restore-tested backup, and the reviewed release/deploy path. The package creates no account, send, booking, charge, or model call.

Next: PR #202 is the release gate. The normal release owner may install only after those account/storage facts are verified.
