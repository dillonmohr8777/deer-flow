### Project Document Evidence Check (`projects/tools.py`, pilot)

`verify_quote(document_id, quote)` is registered beside `list_project_documents`
/ `read_project_document` (same pinned-project resolution, same fail-closed
owner/organization identity, same registration gate, spec §7.3). It checks
whether an exact quote, 20 to 600 characters, appears in one shelf document's
text after folding whitespace runs to a single space and curly/smart quote
characters to straight ones on both sides, then reports the matched character
offsets and about 200 characters of surrounding context in that normalized
text, or a plain not-found result. A document this run cannot read (wrong
owner, wrong organization, wrong project, or trashed) reports the same "no
longer on the shelf" error as a missing document id, never a distinguishable
access-denied response.

What it does not do: a found quote only proves the text exists in the
document. It does not prove the quote supports whatever claim cites it, so
the check is necessary but not sufficient, and the caller still judges
relevance itself.

`projects/context.py::render_evidence_citation_instructions` appends a short
citation instruction (cite as `[doc:<id>]`, call `verify_quote` before relying
on a quote, say plainly when a claim cannot be confirmed) to the transient
per-turn project message, right after the `<documents>` block, and only when
that block itself rendered (a nonempty shelf). It is plain text with no XML
tag wrapper, so unlike `<project>`/`<documents>` it carries no new
`_BLOCKED_TAG_NAMES` entry.
