# Source-bound evidence contract

Status: frozen document contract. This API is not available in the published
runtime. The existing supplied-value evidence-bundle endpoint keeps its behavior.

## Scope and wire surface

`POST /v1/verify/source-bound-evidence` verifies one native-text PDF page and up to
32 exact-span decimal checks. Kernel reparses supplied bytes and verifies SHA-256
and size. A source digest does not prove authenticity or authorization to use the
document; applications must select the authorized source. There is no OCR, search
selector, other format, arbitrary URL or filesystem-path input in this profile.

`GET /v1/verify/source-bound-evidence/capabilities` advertises parser, normalization,
conversion and input limits. The closed schema definitions and route mapping in
this directory specify the complete request/report/error/capability wire shapes.
URNs and draft labels in schema filenames are retained identifiers; contract
content must not change through a cosmetic rename.

## Text and value semantics

Page numbering is 1-based, up to 10,000 and not beyond the actual document. Source
limit is 10 MiB decoded; request-body limit is 14,000,000 bytes. Canonical base64,
source size/SHA and parser identity must match. A page after page 50 may be obtained
through targeted continuation. This does not advertise whole-document completion.

Normalize the complete selected page to NFC and preserve whitespace/line breaks.
Quote/value offsets are absolute Unicode code-point half-open ranges on that page,
not UTF-16 indices, graphemes or PDF bytes. Both spans are nonempty; value is inside
quote. Limits: page text 50,000 code points, quote 4,096, value 64. Lone surrogates,
duplicate keys and non-finite JSON numbers are rejected. The expected normalized
page-text SHA is checked after parsing, never accepted as caller authority.

The entire value span is parsed under ascii_decimal_exact_scale_v1: ASCII decimal
string, at most 18 integral digits, scale 0-8, exactly that many fractional digits.
No grouping, exponent, plus sign, currency inference, trimming or rounding. Source
negative zero becomes positive zero at the same scale; declared negative zero is
malformed. Repeated numbers outside an exact span do not cause ambiguity.

## Results, coverage and identity

A pass proves only that the declared value was derived from the identified span
under the named rule. It does not certify a business role, correctness of the
document, or permission to perform an external action. A false quote cannot pass
because another part of the page contains the same number.

Missing page: 422 PAGE_UNAVAILABLE. Existing OCR-required or incomplete page:
200 review. Quote/value mismatch: 200 fail. Malformed request: 400. Source/parser/
projection identity mismatch: 409. Size limits: 413; unsupported source type: 415;
unreadable/encrypted/resource-limited input: 422; verifier unavailable: 503.
All error codes and HTTP pairings are enumerated in route-mapping.json.

Per-unit status describes native text only. Whole-document disposition remains
partial_unknown, with image_content_not_evaluated and
unselected_document_content_not_evaluated omissions. Selected OCR/clipped units
cannot pass. Aggregation precedence is fail, then review, then pass.

Reports contain ranges, actual source/page/parser identities, conversion/value
facts, quote/value digests and omissions; full quote/source text is not echoed.
Reports and low-entropy hashes can still be sensitive and need access control.

Use RFC 8785/I-JSON for envelope hashes. Semantic request digest excludes request_id
and source.document_b64, retaining all other fields. Semantic result digest hashes
semantic_result only, excluding transport metadata and its own digest. Quote/value
digests are SHA-256 of the actual normalized UTF-8 span. Page identity hashes source
identity, parser contract, normalization, page number and normalized page-text SHA.

## Verification

The reference validator takes independent parser/source context. In a future
runtime that context must be derived from Kernel parsing, never wire assertions.
Synthetic examples, including an incomplete PDF-prefix fixture, exercise contract
shape/semantics and are not successful PDF extraction evidence.

Within this directory, use Python with requirements-contracts.txt and Node with
the devDependencies in package.json. Set PDX_AJV_MODULE_ROOT to a local directory
containing those Node dependencies, then run `python verify_contracts.py`.
No sibling repository, private record, network schema fetch or credential is
required. Contract-freeze hashes use UTF-8 text with universal-newline LF decoding.
Runtime source derivation and clean-install integration remain separate tests.
