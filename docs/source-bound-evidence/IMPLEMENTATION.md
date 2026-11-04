# Source-bound PDF verification implementation candidate

This is an unpublished runtime candidate for review, not a new package release.
Runtime behavior was accepted for source sealing on 2026-11-04. Deployment and
publication remain separate gates. The source release candidate is 0.3.0rc11.
The contract freeze record remains a historical record of the document freeze.
Its schemas, reference validator and examples have not been edited.

The new POST endpoint accepts bytes only, checks canonical base64 and source
identity, independently parses the selected PDF page with pypdf, normalizes to
NFC and applies the frozen code-point-range and exact-decimal rules. The GET
capability endpoint advertises the same frozen limits. The old supplied-value
evidence endpoint is unchanged. No OCR or business-role inference is performed.

Reports bind the actual source and parsed page identities, semantic request and
result digests, and parser/backend versions. No quote or raw source is echoed.
Selected clipped/short-text pages cannot pass. Whole-document disposition stays
partial_unknown. A page after page 50 is directly selected, without claiming
that the rest of the document was inspected.

`tests/test_source_binding_runtime.py` uses actual PDF bytes for correct, forged
and incorrectly declared values, duplicate values with exact ranges, page 55,
blank/OCR-required pages, encrypted input and the HTTP wire. Packaged contracts
are loaded from the installed package; runtime has no dependency on this docs
directory or a neighboring checkout. RFC 8785 is a runtime dependency.

The published package remains the install baseline until the new candidate is
verified on the public package index. Adapter integration is a separate capability.
