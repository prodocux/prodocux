# Portable document intake

The additive Python interface in prodocux_kernel.intake.documents exposes
inspect_document, read_document, resolve_document and document_capabilities.
The matching HTTP prefix is /v1/intake/documents, with capabilities, inspect,
read and resolve operations.

Portable profiles cover UTF-8 TXT/Markdown/log/TSV, inert HTML, JSON/JSONL,
ODT/ODS/ODP, EML, EPUB and plain-text SRT/WebVTT. UTF-8 line reads support bounded
continuation. Other profiles use complete bounded input and disclose omissions;
they reject a continuation descriptor. Existing PDF/DOCX/CSV/XLSX/PPTX projection
APIs remain available. CSV/XLSX v2 are explicitly selected through
contract_version="2"; the default v1 behavior remains compatible.

Inspect is a routing hint and source identity, not a statement of validity.
Read validates the bounded supported subset. Resolve replays from source bytes
and checks the source/parser binding, locator, NFC code-point range and UTF-8
quote digest. Cursors are untrusted range descriptors. Consumers must validate
continuity when aggregating multiple reads.

Inline sources are limited to 4 MiB, and HTML/JSON/JSONL/EML to 1 MiB.
UTF-8 line windows are at most 64 KiB and 512 records, with an 8 KiB physical
line limit. Structured output has 20,000 items and 2 MiB parser output limits;
the read request applies an additional text-byte and item bound. ODF constrains
ZIP entries, expanded bytes, XML size, depth and traversal. JSON has explicit
number, depth and node bounds. EML uses a separate process with a two-second
deadline, 64 KiB top-header limit and 256 top-header lines.

ODF revision histories and deleted text are omitted. Direct ODS table styles
with explicit visibility are evaluated; unknown/inherited visibility is
omitted. EPUB is spine-ordered UTF-8 XHTML, with non-spine resources disclosed.
Timed text accepts plain-text cues in start order and preserves overlaps;
unsupported markup, settings, NOTE/STYLE/REGION blocks are rejected.

RTF/legacy Office conversion and OCR require the separate pdx-document-backend
distribution and an explicit host configuration. The Kernel does not launch
those tools through the portable document HTTP endpoints. Hosts own indexing,
permissions, migration, persistent artifacts and media timeline interpretation.
General ZIP/7z/RAR member extraction is outside these profiles.
