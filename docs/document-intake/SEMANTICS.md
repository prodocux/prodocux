# Portable document intake contract

Inspect reports source identity and a routing hint. It does not validate document
contents or grant access. Read parses only the supported bounded subset. Resolve
reparses supplied source bytes and verifies the source, parser contract, locator,
NFC Unicode-code-point half-open quote range and UTF-8 SHA-256. Digests establish
byte identity, not authorship or domain truth. No network content is fetched.

CSV and XLSX v2 are explicit opt-in through contract_version="2". Existing v1
schemas and validators remain unchanged. CSV v2 treats quoted newlines as part
of a logical record; XLSX v2 reports sheet visibility. PPTX group content remains
omitted and is disclosed as incomplete rather than silently complete.

UTF-8 text windows support continuation. Descriptors are untrusted range
descriptions, not authenticated cursors; hosts validate continuity and bind
source/parser identity. Other portable structured profiles accept bounded whole
sources and reject continuation. Their omissions are disclosed; complete is not
an assertion that every visual or embedded object has been interpreted.

Inline limits, physical-line limits, structured complexity budgets and supported
subsets are described in PORTABLE_DOCUMENT_INTAKE.md and enforced by the parser.
JSON scalar values use deterministic decimal text rather than original lexical
spelling. Quotes bind that projection. Deleted ODF revision history, invisible or
unresolved-visibility sheets and unsupported layout content are not searchable
through this API; omission disclosure remains available to the caller.

RTF/binary Office conversion and image/scanned-PDF OCR are separate, opt-in host
operations. The portable HTTP endpoints do not launch them. A backend result
binds original source, immutable image, parser and derived PDF or OCR geometry.
English OCR can be incomplete and is not source-text certainty. The host owns
persistence, cancellation/recovery, permissions, indexing and final publication.

The freeze manifest records the raw schema digests and RFC 8785 canonical schema
digests. The independent backend manifest records its result schema. New versions
must be additive or explicitly negotiated; existing frozen contracts are not
rewritten by this contract.
