# Template conformance contract proposal

Status: bilaterally frozen with FSF. This freeze does not authorize or claim a
production comparer or implementation release.

FSF consumer provenance (pending PDX verification, not a pin):
`docs/template-conformance/fsf-consumer-provenance.v1.json`.
Home is `D:\FreeStudioFlow\free-studio-flow`, not B-roll.

Scope is PDX-P0b only: normalized template-to-artifact table conformance for
review packs and filled forms. It does not provide prompt-sheet intake,
paragraphs, `-----` separators, embedded-image inventory, or stable paragraph
source ids. PDX-P0a is a separate additive proposal. B-roll must retain its
existing parser until P0a is agreed, implemented, released, and pinned.

The Kernel owns the three packaged schemas. A reference and candidate are
normalized structure profiles; conformance applies an explicit protected vs
allowed policy. File hashes and OOXML byte equality are not conformance.

`OVERFLOW_OR_CLIP` is reserved for renderer-backed evidence. A structure-only
implementation must not claim that check was performed.

Engine integrations reference the result by schema id, payload/report digest,
and immutable artifact identity. They must not copy these schemas.
