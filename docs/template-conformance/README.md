# Template conformance contract proposal

Status: bilaterally frozen with FSF. The production comparer is now an
unpublished ``0.3.0rc6`` candidate; the frozen schema bytes remain unchanged.

The candidate profiles DOCX tables, XLSX worksheet table regions, and PPTX
table shapes into the frozen normalized structure profile. It does not parse
the FSF prompt sheet and does not replace FSF's current intake parser.

FSF consumer provenance (ready for PDX contract seal, not a pin, GitHub not required):
`docs/template-conformance/fsf-consumer-provenance.v1.json`.
Home is `D:\FreeStudioFlow\free-studio-flow` tag `pdx-contract-seal-v1`
(`cf21332fb0764e1b5b19efb1d68b0e1771b5c8d9`), not B-roll.

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
