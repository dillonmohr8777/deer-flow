# Scoped customer reference reads

The `/api/client-references/projects` surface is an opt-in projection of approved
reference documents. Existing staff project routes retain their ordinary RBAC.
Enabling a reference binding does not change a system role, membership, the
global client policy, project editing, run execution or chat/history access.

The operator-controlled `config.yaml` may contain `client_reference_reads`.
`AppConfig` retains this explicit extra section; the router validates it strictly
on every request. It defaults to disabled. Each binding contains an existing
`user_id`, `organization_id`, `project_id`, and `documents`, a map of exact
existing document IDs to their lowercase SHA-256s. Bindings and real identity
values remain private deployment configuration, never public Git content.

```yaml
client_reference_reads:
  enabled: false
  bindings: []
```

Only an authenticated client session whose server-resolved actor and active
organization match a binding may read it. The ordinary active-membership check
still runs first. Storage ownership and organization filtering remain in the
project and document repositories. Caller query strings, headers or JSON cannot
create authority. Conflicting duplicate project bindings fail closed.

Four GET routes are admitted: project list, one project summary, its approved
document list, and one approved document's original content. Project summaries
contain only ID, name and status. Document metadata contains only ID, name,
SHA-256, size and current availability. Counts include approved documents only;
source thread IDs, instructions, internal presentation data, histories, chats
and unapproved rows are not exposed.

Downloads read at most 10 MiB off the event loop, validate original file size
and the approved digest, then return those same bytes as an attachment.
Converted previews never replace the approved original. Missing, oversized or
changed bytes are unavailable, including same-size changes. Responses use
`Cache-Control: no-store` and `X-Content-Type-Options: nosniff`. No sender,
calendar, model or provider is called.

Before activation, capture the current exact project/document IDs and actual
download hashes, approve only the intended reference files, and back up the
operator configuration. After the merged release, read back those hashes and
verify the intended customer session, other-user/org/project/document denial,
and unchanged staff project restrictions. A source test is not customer login
or acceptance. To revoke access, disable the policy or remove its binding;
membership suspension and immutable document replacement also close the read.

Offline coverage: `tests/test_client_reference_policy.py` exercises real host
membership and scoped repositories while RBAC explicitly denies projects:read.
It covers exact actor/org/project/document reads, foreign and unapproved data,
revocation, unknown methods, caller-supplied authority, default-off/malformed
configuration, digest mismatch and same-size filesystem tampering.
