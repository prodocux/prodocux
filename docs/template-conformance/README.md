# Template conformance contract proposal

Status: frozen contract implemented by the current Kernel line; the frozen
schema bytes remain unchanged.

The comparer profiles DOCX tables, XLSX worksheet table regions, and PPTX
table shapes into the frozen normalized structure profile. It does not parse
application-specific prompt sheets and does not replace product intake parsers.

Scope is normalized template-to-artifact table conformance for
review packs and filled forms. It does not provide prompt-sheet intake,
paragraphs, `-----` separators, embedded-image inventory, or stable paragraph
source ids. Consumers retain their existing intake parsers unless a separately
versioned Kernel intake contract is implemented and released.

The Kernel owns the three packaged schemas. A reference and candidate are
normalized structure profiles; conformance applies an explicit protected vs
allowed policy. File hashes and OOXML byte equality are not conformance.

`OVERFLOW_OR_CLIP` is reserved for renderer-backed evidence. A structure-only
implementation must not claim that check was performed.

Engine integrations reference the result by schema id, payload/report digest,
and immutable artifact identity. They must not copy these schemas.
