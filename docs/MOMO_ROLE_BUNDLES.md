# MomoBot Max role bundles v1

This directory contains five source-only role-context profiles for the existing `momobot-max` surface, one manifest, and 21 fully synthetic acceptance contracts. It does not create agents or change runtime state. The profiles add work context only; permissions, model configuration, usage limits, scheduling, and action approvals remain controlled by the existing platform.

## Bundle contents

- `profiles/*.v1.md` has one concise profile per role. Each is checked against the current 4,096-byte UTF-8 prompt ceiling.
- `manifest.v1.json` binds exact role identities to profile hashes and byte counts, records private or tenant workspace gates, and points to the source contracts.
- `acceptance-cases.v1.json` describes synthetic positive and rejection cases for research and code evidence, agency/commercial review, CRM pipeline and proposal handoffs, operations/capacity reporting, and Northwind referral/tour/stop/status workflows.

Fixtures use `SYN-*` identifiers and invented records only. They are not client records, test runs, or evidence of agent behavior. The sales lead's expected CRM portal binding stays private and must be compared with a fresh connector identity readback; no portal ID or credential locator belongs in this bundle.

## Applying a profile requires live identity and storage checks

These files are staged artifacts, not a `USER.md` replacement. Before any owner-approved application, preserve and review the person's existing profile content, then verify the authenticated identity and effective storage principal. Each staff profile requires that person's verified private workspace. The Northwind profile requires an authorized Northwind tenant workspace, verified tenant membership, and a Northwind-only effective storage principal. Never use a global shared `USER.md` or Dillon's private workspace for Northwind.

The current profile surface uses `GET` and `PUT /api/user-profile`, with request body `{"content":"..."}`. A `GET` response can fall back to the legacy shared `USER.md`, so its text alone does not prove per-user or tenant provenance. Confirm the effective storage principal and the actual source path with runtime evidence, preserve existing content, apply only after the proper owner review, and read back through the same identity. Stop if identity, workspace, source path, or tenant isolation is uncertain.

A profile cannot authorize a message, CRM write, publication, contract, invoice, collection, or spend. Keep each such action under current platform permissions and its existing action-specific approval.

## Verification

Run the focused contract checks from `backend/`:

```bash
python -m pytest tests/test_role_bundles.py -q
```

The test checks the five exact identities, role isolation gates, file hashes and byte counts, synthetic scenario structure and coverage, registered profile routes, the `AgentResponse` and `UserProfile*` Pydantic shapes, and the runtime prompt byte limit. These checks validate artifact integrity and declared contracts only. In particular, validating an `AgentResponse` shape does not prove that a live built-in agent is present; fixture assertions do not execute the role or prove business behavior.

Live acceptance still requires identity and storage-principal readback for each staff workspace; Northwind tenant membership and isolation proof; a private expected-portal binding matched against the sales lead's live connector; and human-reviewed scenario runs in the authorized workspaces. No profile write, agent creation, deployment, or live functional run was performed for this source-only bundle.
